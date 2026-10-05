package com.mazlabz.hexplayer.network

import com.mazlabz.hexplayer.model.CardAction
import com.mazlabz.hexplayer.model.CardMapping
import com.mazlabz.hexplayer.model.MediaPlayer
import com.mazlabz.hexplayer.model.PlayerState
import com.mazlabz.hexplayer.model.SpotifyDevice
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

object TransportPolicy {
    fun validate(base: String, hasCredentials: Boolean) {
        val url = java.net.URI(base)
        require(url.scheme in listOf("http", "https") && !url.host.isNullOrBlank() && url.userInfo == null && url.query == null && url.fragment == null) { "Enter an HTTP(S) server URL without credentials, query or fragment" }
        val loopback = url.host in listOf("localhost", "127.0.0.1", "[::1]", "::1")
        require(!hasCredentials || url.scheme == "https" || loopback) { "Credentials require HTTPS or a loopback tunnel. Use manual server setup for trusted LAN HTTP." }
    }
}
internal class JsonHttpClient(private val baseUrl: String, private val bearer: String) {
    fun requestValue(method: String, path: String, body: JSONObject? = null): Any {
        val base = baseUrl.trim().trimEnd('/')
        TransportPolicy.validate(base, bearer.isNotBlank())
        val conn = URL(base + path).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.instanceFollowRedirects = false
            conn.connectTimeout = 6000
            conn.readTimeout = 9000
            conn.setRequestProperty("Accept", "application/json")
            if (bearer.isNotBlank()) conn.setRequestProperty("Authorization", "Bearer $bearer")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                // Never reflect server response bodies which can include upstream secrets.
                val reason = when (code) {
                    400 -> "Invalid request; check the mapping fields"
                    401, 403 -> "Access denied; check credentials and secure server setup"
                    404 -> "Mapping or endpoint not found"
                    502 -> "Upstream playback / Home Assistant request failed"
                    503 -> "Service is not configured or unavailable"
                    in 300..399 -> "Redirect refused; enter the final HTTPS server URL"
                    else -> "Server request failed"
                }
                throw IOException("HTTP $code: $reason")
            }
            return if (text.isBlank()) JSONObject() else org.json.JSONTokener(text).nextValue()
        } finally { conn.disconnect() }
    }
    fun request(method: String, path: String, body: JSONObject? = null): JSONObject =
        requestValue(method, path, body) as? JSONObject ?: throw IOException("Server returned an unexpected JSON schema")
}
class HexPlayerClient(private val baseUrl: String, apiKey: String) {
    private val http = JsonHttpClient(baseUrl, apiKey)

    fun health(): Boolean = http.request("GET", "/api/v1/health").optBoolean("ok")

    fun cards(): List<CardMapping> {
        val cards = http.request("GET", "/api/v1/cards").getJSONObject("cards")
        return cards.keys().asSequence().map { uid ->
            val card = cards.getJSONObject(uid)
            CardMapping(
                uid = uid,
                name = card.optString("name"),
                action = CardAction.fromJson(card.getJSONObject("action")),
            )
        }.toList().sortedBy { it.name.ifBlank { it.uid } }
    }

    fun upsert(card: CardMapping) {
        val body = JSONObject().put("name", card.name).put("action", card.action.toJson())
        http.request("PUT", "/api/v1/cards/${card.uid}", body)
    }

    fun delete(uid: String) { http.request("DELETE", "/api/v1/cards/$uid") }
    fun trigger(uid: String) { http.request("POST", "/api/v1/cards/$uid/trigger", JSONObject()) }

    fun spotifyDevices(): List<SpotifyDevice> {
        val arr = http.request("GET", "/api/v1/spotify/devices").getJSONArray("devices")
        return (0 until arr.length()).map { index ->
            val item = arr.getJSONObject(index)
            SpotifyDevice(
                id = item.optString("id"),
                name = item.optString("name"),
                active = item.optBoolean("active"),
                volume = item.optInt("volume", 0),
            )
        }
    }

    fun playerState(): PlayerState {
        val json = http.request("GET", "/api/v1/spotify/state")
        val artists = json.optJSONArray("artists")
        return PlayerState(
            playing = json.optBoolean("playing"),
            device = json.optString("device").takeIf { it.isNotBlank() && it != "null" },
            title = json.optString("title").takeIf { it.isNotBlank() && it != "null" },
            artists = if (artists == null) emptyList() else (0 until artists.length()).map { artists.optString(it) },
        )
    }

    fun spotifyControl(command: String, deviceId: String = "", volume: Int? = null, uri: String = "") {
        val body = JSONObject().put("command", command)
        if (deviceId.isNotBlank()) body.put("device_id", deviceId)
        if (volume != null) body.put("volume", volume)
        if (uri.isNotBlank()) body.put("uri", uri)
        http.request("POST", "/api/v1/spotify/control", body)
    }

    fun provisionHomeAssistant(url: String, token: String) {
        TransportPolicy.validate(baseUrl, true)
        TransportPolicy.validate(url, true)
        http.request("PUT", "/api/v1/home-assistant/config", JSONObject().put("url", url).put("token", token))
    }
}

class HomeAssistantClient(baseUrl: String, token: String) {
    private val http = JsonHttpClient(baseUrl, token)

    fun health(): Boolean = http.request("GET", "/api/").optString("message").isNotBlank()

    fun mediaPlayers(): List<MediaPlayer> {
        val arr = http.requestValue("GET", "/api/states") as? org.json.JSONArray ?: throw IOException("Unexpected states schema")
        return (0 until arr.length()).mapNotNull { index ->
            val state = arr.getJSONObject(index)
            val entityId = state.optString("entity_id")
            if (!entityId.startsWith("media_player.")) return@mapNotNull null
            val attrs = state.optJSONObject("attributes") ?: JSONObject()
            MediaPlayer(
                entityId = entityId,
                name = attrs.optString("friendly_name", entityId),
                state = state.optString("state"),
                volume = if (attrs.has("volume_level") && !attrs.isNull("volume_level")) attrs.optDouble("volume_level") else null,
                mediaTitle = attrs.optString("media_title").takeIf { it.isNotBlank() },
            )
        }.sortedBy { it.name }
    }

    fun service(domain: String, service: String, data: JSONObject) {
        http.requestValue("POST", "/api/services/$domain/$service", data)
    }
}
