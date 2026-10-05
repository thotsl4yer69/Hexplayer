package com.mazlabz.hexplayer.model

import org.json.JSONObject

data class CardMapping(
    val uid: String,
    val name: String,
    val action: CardAction,
)

data class CardAction(
    val type: String,
    val uri: String = "",
    val deviceId: String = "",
    val entityId: String = "",
    val mediaContentId: String = "",
    val mediaContentType: String = "music",
    val domain: String = "",
    val service: String = "",
    val eventType: String = "",
    val dataJson: String = "{}",
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("type", type)
        when (type) {
            "spotify" -> {
                put("uri", uri)
                if (deviceId.isNotBlank()) put("device_id", deviceId)
            }
            "ha_media" -> {
                put("entity_id", entityId)
                put("media_content_id", mediaContentId)
                put("media_content_type", mediaContentType.ifBlank { "music" })
                parseData()?.let { put("data", it) }
            }
            "ha_service" -> {
                put("domain", domain)
                put("service", service)
                if (entityId.isNotBlank()) put("entity_id", entityId)
                parseData()?.let { put("data", it) }
            }
            "ha_event" -> {
                put("event_type", eventType)
                parseData()?.let { put("data", it) }
            }
        }
    }

    private fun parseData(): JSONObject? = if (dataJson.isBlank()) null else JSONObject(dataJson)

    companion object {
        fun fromJson(json: JSONObject): CardAction {
            val data = json.optJSONObject("data")?.toString() ?: "{}"
            return CardAction(
                type = json.optString("type"),
                uri = json.optString("uri"),
                deviceId = json.optString("device_id"),
                entityId = json.optString("entity_id"),
                mediaContentId = json.optString("media_content_id"),
                mediaContentType = json.optString("media_content_type", "music"),
                domain = json.optString("domain"),
                service = json.optString("service"),
                eventType = json.optString("event_type"),
                dataJson = data,
            )
        }
    }
}

data class SpotifyDevice(val id: String, val name: String, val active: Boolean, val volume: Int)

data class MediaPlayer(
    val entityId: String,
    val name: String,
    val state: String,
    val volume: Double?,
    val mediaTitle: String?,
)

data class PlayerState(
    val playing: Boolean,
    val device: String?,
    val title: String?,
    val artists: List<String>,
)

object UidCodec {
    fun normalize(value: String): String? {
        val hex = value.trim().replace("-", "" ).replace(":", "" ).uppercase()
        if (!hex.matches(Regex("[0-9A-F]{8,20}")) || hex.length % 2 != 0) return null
        return hex.chunked(2).joinToString("-")
    }
    fun format(bytes: ByteArray): String = bytes.joinToString("-") { "%02X".format(it.toInt() and 0xFF) }
}
