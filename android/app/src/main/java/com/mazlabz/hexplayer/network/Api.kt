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

private class JsonHttpClient(
    private val baseUrl: String,
    private val bearer: String,
) {
    fun request(method: String, path: String, body: JSONObject? = null): JSONObject {
        val base = baseUrl.trim().trimEnd('/')
        require(base.startsWith("http://") || base.startsWith("https://")) { "Invalid URL" }
        val conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 6000
            readTimeout = 9000
            setRequestProperty("Accept", "application/json")
            if (bearer.isNotBlank()) setRequestProperty("Authorization", "Bearer $bearer")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
        }
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IOException("HTTP $code: ${text.take(400)}")
            if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }
}

class HexPlayerClient(baseUrl: String, apiKey: String) {
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
        http.request("PUT", "/api/v1/home-assistant/config", JSONObject().put("url", url).put("token", token))
    }
}

class HomeAssistantClient(baseUrl: String, token: String) {
    private val http = JsonHttpClient(baseUrl, token)

    fun health(): Boolean = http.request("GET", "/api/").optString("message").isNotBlank()

    fun mediaPlayers(): List<MediaPlayer> {
        val base = baseUrlForRaw()
        val conn = (URL("$base/api/states").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 6000
            readTimeout = 9000
            setRequestProperty("Authorization", "Bearer ${tokenForRaw()}")
            setRequestProperty("Accept", "application/json")
        }
        try {
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream).bufferedReader().use { it.readText() }
            if (code !in 200..299) throw IOException("HTTP $code: ${text.take(400)}")
            val arr = org.json.JSONArray(text)
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
        } finally {
            conn.disconnect()
        }
    }

    fun service(domain: String, service: String, data: JSONObject) {
        http.request("POST", "/api/services/$domain/$service", data)
    }

    // Kept private so credentials remain encapsulated in this client.
    private val rawBase: String = baseUrl.trim().trimEnd('/')
    private val rawToken: String = token
    private fun baseUrlForRaw() = rawBase
    private fun tokenForRaw() = rawToken
}
