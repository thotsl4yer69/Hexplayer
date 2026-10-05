package com.mazlabz.hexplayer

import android.nfc.NfcAdapter
import android.nfc.Tag
import android.os.Bundle
import android.view.WindowManager
import androidx.compose.foundation.layout.safeDrawingPadding
import com.mazlabz.hexplayer.nfc.NfcSession
import com.mazlabz.hexplayer.model.UidCodec
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.mazlabz.hexplayer.model.CardAction
import com.mazlabz.hexplayer.model.CardMapping
import com.mazlabz.hexplayer.model.MediaPlayer
import com.mazlabz.hexplayer.model.PlayerState
import com.mazlabz.hexplayer.model.SpotifyDevice
import com.mazlabz.hexplayer.network.TransportPolicy
import com.mazlabz.hexplayer.network.HexPlayerClient
import com.mazlabz.hexplayer.network.HomeAssistantClient
import com.mazlabz.hexplayer.nfc.NfcTools
import com.mazlabz.hexplayer.storage.SecureSettings
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private enum class Tab { DASHBOARD, CARDS, SPEAKERS, SETTINGS }
    private enum class NfcMode { IDLE, SCAN, WRITE }

    private lateinit var settings: SecureSettings
    private val executor = Executors.newSingleThreadExecutor()
    private var adapter: NfcAdapter? = null

    private val nfcSession = NfcSession()
    private var nfcAvailable by mutableStateOf(false)
    private var nfcMode by mutableStateOf(NfcMode.IDLE)
    @Volatile private var expectedWriteUid = ""

    private var tab by mutableStateOf(Tab.DASHBOARD)
    private var message by mutableStateOf("Ready")
    private var hexOnline by mutableStateOf(false)
    private var haOnline by mutableStateOf(false)
    private var cards by mutableStateOf<List<CardMapping>>(emptyList())
    private var devices by mutableStateOf<List<SpotifyDevice>>(emptyList())
    private var speakers by mutableStateOf<List<MediaPlayer>>(emptyList())
    private var playerState by mutableStateOf<PlayerState?>(null)

    private var hexUrl by mutableStateOf("http://hexplayer.local:8787")
    private var apiKey by mutableStateOf("")
    private var haUrl by mutableStateOf("http://homeassistant.local:8123")
    private var haToken by mutableStateOf("")
    private var selectedDeviceId by mutableStateOf("")

    private var editorGeneration = 0L
    private var editUid by mutableStateOf("")
    private var editName by mutableStateOf("")
    private var editType by mutableStateOf("spotify")
    private var editUri by mutableStateOf("")
    private var editDeviceId by mutableStateOf("")
    private var editEntityId by mutableStateOf("")
    private var editMediaId by mutableStateOf("")
    private var editMediaType by mutableStateOf("music")
    private var editDomain by mutableStateOf("")
    private var editService by mutableStateOf("")
    private var editEventType by mutableStateOf("")
    private var editData by mutableStateOf("{}")

    private var speakerMediaId by mutableStateOf("")
    private var speakerMediaType by mutableStateOf("music")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        settings = SecureSettings(this)
        adapter = NfcAdapter.getDefaultAdapter(this)
        hexUrl = settings.getUrl("hex", hexUrl)
        apiKey = settings.getSecret("api_key")
        haUrl = settings.getUrl("ha", haUrl)
        haToken = settings.getSecret("ha_token")

        if (savedInstanceState != null) {
            editUid = savedInstanceState.getString("draft_editUid", editUid) ?: editUid
            editName = savedInstanceState.getString("draft_editName", editName) ?: editName
            editType = savedInstanceState.getString("draft_editType", editType) ?: editType
            editUri = savedInstanceState.getString("draft_editUri", editUri) ?: editUri
            editDeviceId = savedInstanceState.getString("draft_editDeviceId", editDeviceId) ?: editDeviceId
            editEntityId = savedInstanceState.getString("draft_editEntityId", editEntityId) ?: editEntityId
            editMediaId = savedInstanceState.getString("draft_editMediaId", editMediaId) ?: editMediaId
            editMediaType = savedInstanceState.getString("draft_editMediaType", editMediaType) ?: editMediaType
            editDomain = savedInstanceState.getString("draft_editDomain", editDomain) ?: editDomain
            editService = savedInstanceState.getString("draft_editService", editService) ?: editService
            editEventType = savedInstanceState.getString("draft_editEventType", editEventType) ?: editEventType
            editData = savedInstanceState.getString("draft_editData", editData) ?: editData
            tab = runCatching { Tab.valueOf(savedInstanceState.getString("tab", "DASHBOARD")) }.getOrDefault(Tab.DASHBOARD)
        }
        setContent {
            MaterialTheme { HexPlayerApp() }
        }
        refreshAll()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        // Preserve raw draft text, including invalid JSON, without saving credentials.
        outState.putString("draft_editUid", editUid)
        outState.putString("draft_editName", editName)
        outState.putString("draft_editType", editType)
        outState.putString("draft_editUri", editUri)
        outState.putString("draft_editDeviceId", editDeviceId)
        outState.putString("draft_editEntityId", editEntityId)
        outState.putString("draft_editMediaId", editMediaId)
        outState.putString("draft_editMediaType", editMediaType)
        outState.putString("draft_editDomain", editDomain)
        outState.putString("draft_editService", editService)
        outState.putString("draft_editEventType", editEventType)
        outState.putString("draft_editData", editData)
        outState.putString("tab", tab.name)
        super.onSaveInstanceState(outState)
    }

    override fun onResume() {
        super.onResume()
        nfcAvailable = adapter?.isEnabled == true
        if (nfcAvailable) adapter?.enableReaderMode(
            this,
            { tag -> handleTag(tag) },
            NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_NFC_V,
            null,
        )
    }

    override fun onPause() {
        editorGeneration++
        cancelNfc()
        adapter?.disableReaderMode(this)
        super.onPause()
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun cancelNfc() {
        nfcSession.cancel()
        expectedWriteUid = ""
        if (nfcMode != NfcMode.IDLE) message = "NFC cancelled. A write already in progress may have reached the tag; scan to check."
        nfcMode = NfcMode.IDLE
    }

    private fun armNfc(write: Boolean = false) {
        if (adapter?.isEnabled != true) {
            message = if (adapter == null) "No NFC hardware. Enter a UID manually." else "NFC is disabled. Enable NFC in Android settings."
            return
        }
        val uid = if (write) UidCodec.normalize(editUid) else null
        if (write && uid == null) { message = "Enter a valid hexadecimal UID first"; return }
        expectedWriteUid = uid.orEmpty()
        nfcSession.arm(uid)
        nfcMode = if (write) NfcMode.WRITE else NfcMode.SCAN
        message = if (write) "Retap $uid. This replaces the tag's NDEF contents; keep it still until verified." else "Tap a tag to read its UID and NDEF contents"
    }

    private fun handleTag(tag: Tag) {
        val uid = NfcTools.uid(tag)
        val operation = nfcSession.claim(uid) ?: run {
            if (expectedWriteUid.isNotBlank() && expectedWriteUid != uid) runOnUiThread {
                if (nfcMode == NfcMode.WRITE) message = "Wrong tag: expected $expectedWriteUid, saw $uid. Retap the intended tag or cancel."
            }
            return
        }
        if (UidCodec.normalize(uid) == null) {
            runOnUiThread {
                if (nfcSession.isCurrent(operation) && !isDestroyed) {
                    cancelNfc()
                    message = "Invalid or empty physical tag UID; no mapping or write performed"
                }
            }
            return
        }
        val result = if (operation.writeUid != null) {
            NfcTools.writeHexPlayerUri(tag, uid).fold(
                { "NFC programmed and read-back verified: hexplayer://card/$uid" },
                { "Write not verified: ${it.message}. Scan again to check the tag." })
        } else NfcTools.read(tag).fold({ "Read $uid: $it" }, { "UID $uid: ${it.message}" })
        runOnUiThread {
            if (!nfcSession.isCurrent(operation) || isDestroyed) return@runOnUiThread
            nfcMode = NfcMode.IDLE
            if (operation.writeUid == null) {
                cards.find { it.uid == uid }?.let { loadEditor(it) } ?: resetEditor(uid)
                tab = Tab.CARDS
            }
            message = result
        }
    }
    private fun hexClient() = HexPlayerClient(hexUrl, apiKey)
    private fun haClient() = HomeAssistantClient(haUrl, haToken)

    private fun refreshAll() {
        val generation = editorGeneration
        val hex = hexClient()
        val ha = haClient()
        executor.execute {
            var hOk = false
            var aOk = false
            var newCards = emptyList<CardMapping>()
            var newDevices = emptyList<SpotifyDevice>()
            var newSpeakers = emptyList<MediaPlayer>()
            var newState: PlayerState? = null
            val errors = mutableListOf<String>()

            try {
                val client = hex
                hOk = client.health()
                if (apiKey.isNotBlank()) {
                    newCards = client.cards()
                    try { newDevices = client.spotifyDevices(); newState = client.playerState() }
                    catch (exc: Exception) { errors += "Spotify: ${exc.message}" }
                } else errors += "Enter the HexPlayer API key in Settings"
            } catch (exc: Exception) {
                errors += "HexPlayer: ${exc.message}"
            }

            if (haToken.isNotBlank()) {
                try {
                    val client = ha
                    aOk = client.health()
                    newSpeakers = client.mediaPlayers()
                } catch (exc: Exception) {
                    errors += "Home Assistant: ${exc.message}"
                }
            }

            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                hexOnline = hOk
                haOnline = aOk
                cards = newCards
                devices = newDevices
                speakers = newSpeakers
                playerState = newState
                if (selectedDeviceId.isBlank()) selectedDeviceId = devices.firstOrNull { it.active }?.id.orEmpty()
                if (editorGeneration == generation) message = if (errors.isEmpty()) "Synced" else errors.joinToString(" | ")
            }
        }
    }

    private fun resetEditor(uid: String = "") {
        editorGeneration++
        editUid = uid
        editName = ""
        editType = "spotify"
        editUri = ""
        editDeviceId = ""
        editEntityId = ""
        editMediaId = ""
        editMediaType = "music"
        editDomain = ""
        editService = ""
        editEventType = ""
        editData = "{}"
    }

    private fun loadEditor(card: CardMapping) {
        editorGeneration++
        cancelNfc()
        editUid = card.uid
        editName = card.name
        editType = card.action.type
        editUri = card.action.uri
        editDeviceId = card.action.deviceId
        editEntityId = card.action.entityId
        editMediaId = card.action.mediaContentId
        editMediaType = card.action.mediaContentType
        editDomain = card.action.domain
        editService = card.action.service
        editEventType = card.action.eventType
        editData = card.action.dataJson
    }

    private fun currentAction(): CardAction {
        if (editType != "spotify" && editData.isNotBlank()) JSONObject(editData)
        return CardAction(
            type = editType,
            uri = editUri.trim(),
            deviceId = editDeviceId.trim(),
            entityId = editEntityId.trim(),
            mediaContentId = editMediaId.trim(),
            mediaContentType = editMediaType.trim().ifBlank { "music" },
            domain = editDomain.trim(),
            service = editService.trim(),
            eventType = editEventType.trim(),
            dataJson = if (editType == "spotify") "{}" else editData.ifBlank { "{}" },
        )
    }

    private fun saveCard() {
        if (UidCodec.normalize(editUid) == null) {
            message = "Scan a tag or enter a hexadecimal UID (e.g. 04-A1-B2-C3)"
            return
        }
        val action = try { currentAction() } catch (exc: Exception) {
            message = "Invalid JSON data: ${exc.message}"
            return
        }
        val validation = when (action.type) {
            "spotify" -> if (!action.uri.matches(Regex("spotify:(track|album|playlist|artist):[A-Za-z0-9]+"))) "Enter a Spotify track, album, playlist or artist URI" else if (action.deviceId.isBlank()) "Choose or enter a Spotify playback device ID" else null
            "ha_media" -> if (!action.entityId.startsWith("media_player.") || action.mediaContentId.isBlank()) "Choose a speaker and media item" else null
            "ha_service" -> if (action.domain.isBlank() || action.service.isBlank()) "Domain and service are required" else null
            "ha_event" -> if (action.eventType.isBlank()) "Event type is required" else null
            else -> "Unsupported action type"
        }
        if (validation != null) {
            message = validation
            return
        }
        val card = CardMapping(UidCodec.normalize(editUid)!!, editName.trim(), action)
        val generation = editorGeneration
        val client = hexClient()
        executor.execute {
            try {
                client.upsert(card)
                runOnUiThread { if (!isDestroyed && editorGeneration == generation) { message = "Saved ${card.uid}"; refreshAll() } }
            } catch (exc: Exception) {
                runOnUiThread { if (!isDestroyed && editorGeneration == generation) message = "Save failed: ${exc.message}. Reload mappings before retrying; the server may have received the save." }
            }
        }
    }

    private fun deleteCard(uid: String) {
        val generation = editorGeneration
        val client = hexClient()
        val normalized = UidCodec.normalize(uid) ?: run { message = "Invalid UID"; return }
        executor.execute {
            try {
                client.delete(normalized)
                runOnUiThread { if (!isDestroyed && editorGeneration == generation) { resetEditor(); message = "Deleted $uid"; refreshAll() } }
            } catch (exc: Exception) {
                runOnUiThread { if (!isDestroyed && editorGeneration == generation) message = "Delete failed: ${exc.message}. Reload before retrying." }
            }
        }
    }

    private fun triggerCard(uid: String) {
        val client = hexClient()
        val normalized = UidCodec.normalize(uid) ?: run { message = "Invalid UID"; return }
        executor.execute {
            try {
                client.trigger(normalized)
                runOnUiThread { message = "Triggered $uid" }
            } catch (exc: Exception) {
                runOnUiThread { message = "Trigger request failed: ${exc.message}. Action may have executed; check the target before retrying." }
            }
        }
    }

    private fun spotify(command: String) {
        val target = selectedDeviceId
        val client = hexClient()
        if (selectedDeviceId.isBlank()) { message = "Choose a Spotify playback target first"; return }
        executor.execute {
            try {
                client.spotifyControl(command, target)
                runOnUiThread { message = "Spotify: $command" }
                Thread.sleep(350)
                try {
                    val state = hexClient().playerState()
                    runOnUiThread { playerState = state }
                } catch (_: Exception) { }
            } catch (exc: Exception) {
                runOnUiThread { message = "Spotify request failed: ${exc.message}. Action may have executed; check the target before retrying." }
            }
        }
    }

    private fun haService(domain: String, service: String, data: JSONObject, success: String) {
        val client = haClient()
        executor.execute {
            try {
                client.service(domain, service, data)
                runOnUiThread { message = success }
                refreshAll()
            } catch (exc: Exception) {
                runOnUiThread { message = "Home Assistant request failed: ${exc.message}. Action may have executed; check the target before retrying." }
            }
        }
    }

    private fun saveSettings() {
        try {
            TransportPolicy.validate(hexUrl.trim(), apiKey.isNotBlank())
            TransportPolicy.validate(haUrl.trim(), haToken.isNotBlank())
        } catch (exc: Exception) { message = exc.message ?: "Invalid settings"; return }
        try {
        settings.putUrl("hex", hexUrl)
        settings.putSecret("api_key", apiKey)
        settings.putUrl("ha", haUrl)
        settings.putSecret("ha_token", haToken)
        } catch (exc: Exception) { message = "Secure settings could not be saved; please retry"; return }
        message = "Settings saved"
        refreshAll()
    }

    private fun provisionHomeAssistant() {
        val client = hexClient()
        val targetUrl = haUrl
        val targetToken = haToken
        if (haUrl.isBlank() || haToken.isBlank()) {
            message = "Home Assistant URL and token are required"
            return
        }
        executor.execute {
            try {
                client.provisionHomeAssistant(targetUrl, targetToken)
                runOnUiThread { message = "Home Assistant credentials provisioned to HexPlayer" }
            } catch (exc: Exception) {
                runOnUiThread { message = "Provisioning failed: ${exc.message}" }
            }
        }
    }

    @Composable
    private fun HexPlayerApp() {
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(12.dp)) {
            Text("HEXPLAYER", style = MaterialTheme.typography.headlineMedium)
            Text(message, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                TabButton("Player", Tab.DASHBOARD)
                TabButton("Cards", Tab.CARDS)
                TabButton("Speakers", Tab.SPEAKERS)
                TabButton("Settings", Tab.SETTINGS)
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            when (tab) {
                Tab.DASHBOARD -> DashboardScreen()
                Tab.CARDS -> CardsScreen()
                Tab.SPEAKERS -> SpeakersScreen()
                Tab.SETTINGS -> SettingsScreen()
            }
        }
    }

    @Composable
    private fun TabButton(label: String, target: Tab) {
        if (tab == target) Button(onClick = { cancelNfc(); tab = target }) { Text(label) }
        else TextButton(onClick = { cancelNfc(); tab = target }) { Text(label) }
    }

    @Composable
    private fun DashboardScreen() {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("Connections", style = MaterialTheme.typography.titleMedium)
                    Text("HexPlayer: ${if (hexOnline) "online" else "offline"}")
                    Text("Home Assistant: ${if (haOnline) "online" else "offline / not configured"}")
                    Text("Registered cards: ${cards.size}")
                    Button(onClick = { refreshAll() }) { Text("Refresh") }
                }
            }

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Now playing", style = MaterialTheme.typography.titleMedium)
                    Text(playerState?.title ?: "Nothing reported")
                    if (!playerState?.artists.isNullOrEmpty()) Text(playerState!!.artists.joinToString(", "))
                    Text(playerState?.device ?: "No active Spotify device")
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Button(onClick = { spotify("previous") }) { Text("Prev") }
                        Button(onClick = { spotify(if (playerState?.playing == true) "pause" else "play") }) { Text(if (playerState?.playing == true) "Pause" else "Play") }
                        Button(onClick = { spotify("next") }) { Text("Next") }
                    }
                    OutlinedTextField(selectedDeviceId, { selectedDeviceId = it }, label = { Text("Playback target device ID") }, modifier = Modifier.fillMaxWidth())
                    if (devices.isNotEmpty()) {
                        Text("Target Spotify device")
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            devices.forEach { device ->
                                TextButton(onClick = { selectedDeviceId = device.id }) {
                                    Text(if (selectedDeviceId == device.id) "[${device.name}]" else device.name)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun CardsScreen() {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    armNfc()
                }) { Text("Scan new card") }
                TextButton(onClick = { cancelNfc(); resetEditor() }) { Text("Clear editor") }
            }
            if (!nfcAvailable) Text(if (adapter == null) "No NFC hardware. Manual mapping and remote control remain available." else "NFC is disabled. Enable it in Android settings, or enter a UID manually.")
            if (nfcMode != NfcMode.IDLE) TextButton(onClick = { cancelNfc() }) { Text("Cancel NFC") }
            Text("Supports NDEF-formatted NFC tags only. This does not clone RFID chips. Mapping is saved on HexPlayer; NFC programming writes a label only.")
            OutlinedTextField(editUid, { editorGeneration++; cancelNfc(); editUid = it }, label = { Text("Tag UID (scan or enter manually)") }, modifier = Modifier.fillMaxWidth())

            cards.forEach { card ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(card.name.ifBlank { card.uid }, style = MaterialTheme.typography.titleSmall)
                        Text("${card.uid} · ${card.action.type}")
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            TextButton(onClick = { loadEditor(card) }) { Text("Edit") }
                            TextButton(onClick = { triggerCard(card.uid) }) { Text("Run action") }
                        }
                    }
                }
            }

            if (editUid.isNotBlank()) {
                HorizontalDivider()
                Text("Card editor", style = MaterialTheme.typography.titleLarge)
                Text("UID: $editUid")
                OutlinedTextField(editName, { editorGeneration++; cancelNfc(); editName = it }, label = { Text("Card name") }, modifier = Modifier.fillMaxWidth())
                Text("Action")
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    ActionButton("Spotify", "spotify")
                    ActionButton("Speaker", "ha_media")
                    ActionButton("HA service", "ha_service")
                    ActionButton("HA event", "ha_event")
                }

                when (editType) {
                    "spotify" -> {
                        OutlinedTextField(editUri, { editorGeneration++; cancelNfc(); editUri = it }, label = { Text("Spotify URI") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editDeviceId, { editorGeneration++; cancelNfc(); editDeviceId = it }, label = { Text("Spotify device ID (required)") }, modifier = Modifier.fillMaxWidth())

                    if (devices.isNotEmpty()) {
                            Row(Modifier.horizontalScroll(rememberScrollState())) {
                                devices.forEach { d -> TextButton(onClick = { editorGeneration++; cancelNfc(); editDeviceId = d.id }) { Text(d.name) } }
                            }
                        }
                    }
                    "ha_media" -> {
                        OutlinedTextField(editEntityId, { editorGeneration++; cancelNfc(); editEntityId = it }, label = { Text("media_player entity") }, modifier = Modifier.fillMaxWidth())
                        if (speakers.isNotEmpty()) {
                            Row(Modifier.horizontalScroll(rememberScrollState())) {
                                speakers.forEach { s -> TextButton(onClick = { editorGeneration++; cancelNfc(); editEntityId = s.entityId }) { Text(s.name) } }
                            }
                        }
                        OutlinedTextField(editMediaId, { editorGeneration++; cancelNfc(); editMediaId = it }, label = { Text("Media content ID / URI") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editMediaType, { editorGeneration++; cancelNfc(); editMediaType = it }, label = { Text("Media content type") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editData, { editorGeneration++; cancelNfc(); editData = it }, label = { Text("Extra service data JSON") }, modifier = Modifier.fillMaxWidth())
                    }
                    "ha_service" -> {
                        OutlinedTextField(editDomain, { editorGeneration++; cancelNfc(); editDomain = it }, label = { Text("Domain (e.g. script)") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editService, { editorGeneration++; cancelNfc(); editService = it }, label = { Text("Service (e.g. turn_on)") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editEntityId, { editorGeneration++; cancelNfc(); editEntityId = it }, label = { Text("Entity ID (optional)") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editData, { editorGeneration++; cancelNfc(); editData = it }, label = { Text("Service data JSON") }, modifier = Modifier.fillMaxWidth())
                    }
                    "ha_event" -> {
                        OutlinedTextField(editEventType, { editorGeneration++; cancelNfc(); editEventType = it }, label = { Text("Event type") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(editData, { editorGeneration++; cancelNfc(); editData = it }, label = { Text("Event data JSON") }, modifier = Modifier.fillMaxWidth())
                    }
                }

                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Button(onClick = { saveCard() }) { Text("Save mapping") }
                    Button(onClick = {
                        armNfc(write = true)
                    }) { Text("Program NFC") }
                    TextButton(onClick = { triggerCard(editUid) }) { Text("Run saved action") }
                    TextButton(onClick = { deleteCard(editUid) }) { Text("Delete") }
                }
            }
        }
    }

    @Composable
    private fun ActionButton(label: String, value: String) {
        if (editType == value) Button(onClick = { editorGeneration++; cancelNfc(); editType = value }) { Text(label) }
        else TextButton(onClick = { editorGeneration++; cancelNfc(); editType = value }) { Text(label) }
    }

    @Composable
    private fun SpeakersScreen() {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(speakerMediaId, { speakerMediaId = it }, label = { Text("Media URI / content ID") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(speakerMediaType, { speakerMediaType = it }, label = { Text("Content type") }, modifier = Modifier.fillMaxWidth())
            Button(onClick = { refreshAll() }) { Text("Refresh speakers") }

            speakers.forEach { speaker ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(speaker.name, style = MaterialTheme.typography.titleMedium)
                        Text("${speaker.entityId} · ${speaker.state}${speaker.mediaTitle?.let { " · $it" } ?: ""}")
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            Button(onClick = {
                                haService("media_player", "media_play_pause", JSONObject().put("entity_id", speaker.entityId), "Toggled ${speaker.name}")
                            }) { Text("Play/Pause") }
                            TextButton(onClick = {
                                haService("media_player", "media_stop", JSONObject().put("entity_id", speaker.entityId), "Stopped ${speaker.name}")
                            }) { Text("Stop") }
                            TextButton(onClick = {
                                if (speakerMediaId.isBlank()) message = "Enter a media URI/content ID first"
                                else haService(
                                    "media_player", "play_media",
                                    JSONObject()
                                        .put("entity_id", speaker.entityId)
                                        .put("media_content_id", speakerMediaId)
                                        .put("media_content_type", speakerMediaType.ifBlank { "music" }),
                                    "Sent media to ${speaker.name}",
                                )
                            }) { Text("Send") }
                        }
                    }
                }
            }
            if (speakers.isEmpty()) Text("No Home Assistant media_player entities loaded.")
        }
    }

    @Composable
    private fun SettingsScreen() {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("HexPlayer", style = MaterialTheme.typography.titleMedium)
            Text("Use HTTPS for credentials (or a loopback tunnel). Enter your own tokens; they are encrypted using Android Keystore. Manual configuration works without a player connection.")
            OutlinedTextField(hexUrl, { hexUrl = it }, label = { Text("HexPlayer URL") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(apiKey, { apiKey = it }, label = { Text("HexPlayer API key") }, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())

            Text("Home Assistant", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(haUrl, { haUrl = it }, label = { Text("Home Assistant URL") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(haToken, { haToken = it }, label = { Text("Long-lived access token") }, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())

            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = { saveSettings() }) { Text("Save + test") }
                Button(onClick = { provisionHomeAssistant() }) { Text("Provision HA to HexPlayer") }
            }
            Text("Provisioning requires the daemon behind its trusted HTTPS proxy. Alternatively configure HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN manually on the player. Credentials are stored on the player so saved mappings can work without this phone.")
        }
    }
}
