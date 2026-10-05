package com.mazlabz.hexplayer

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ControllerUiTest {
    private lateinit var server: HttpServer
    @Volatile private var stored: JSONObject? = null
    @Volatile private var triggeredTarget: String? = null
    @Volatile private var saveRequests = 0
    @Volatile private var rejectSaves = false
    @get:Rule(order = 0) val mockServer = object : org.junit.rules.ExternalResource() {
        override fun before() {
            server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
            server.createContext("/api/v1/") { exchange ->
                var status = 200
                val response = when {
                    exchange.requestURI.path.endsWith("health") -> "{\"ok\":true}"
                    exchange.requestURI.path.endsWith("trigger") -> {
                        triggeredTarget = stored!!.getJSONObject("action").getString("device_id")
                        "{}"
                    }
                    exchange.requestMethod == "PUT" -> {
                        saveRequests++
                        if (rejectSaves) status = 503
                        else stored = JSONObject(exchange.requestBody.bufferedReader().readText())
                        "{}"
                    }
                    exchange.requestURI.path.endsWith("cards") -> JSONObject().put("cards", JSONObject().also { stored?.let { card -> it.put("04-AA-BB-CC", card) } }).toString()
                    exchange.requestURI.path.endsWith("devices") -> "{\"devices\":[]}"
                    else -> "{}"
                }
                val bytes = response.toByteArray(); exchange.sendResponseHeaders(status, bytes.size.toLong())
                exchange.responseBody.use { it.write(bytes) }
            }
            server.start()
            org.robolectric.RuntimeEnvironment.getApplication().getSharedPreferences("hexplayer_settings", 0)
                .edit().clear().putString("url_hex", "http://127.0.0.1:${server.address.port}").commit()
        }
        override fun after() { server.stop(0) }
    }
    @get:Rule(order = 1) val compose = createAndroidComposeRule<MainActivity>()
    private fun awaitInitialRefresh() {
        compose.waitUntil(10000) { compose.onAllNodesWithText("Enter the HexPlayer API key in Settings", substring = true).fetchSemanticsNodes().isNotEmpty() }
    }
    @Test fun manualInvalidUidAndClearEditorWorkWithoutNfc() {
        awaitInitialRefresh()
        compose.onNodeWithText("Cards", useUnmergedTree=true).performClick()
        compose.onNodeWithText("Tag UID (scan or enter manually)").performTextInput("invalid")
        compose.onNodeWithText("Save mapping").performScrollTo().performClick()
        compose.onNodeWithText("Scan a tag or enter a hexadecimal UID (e.g. 04-A1-B2-C3)").assertExists()
        compose.onNodeWithText("Clear editor").performScrollTo().performClick()
        compose.onNodeWithText("Save mapping").assertDoesNotExist()
    }
    private fun enterMapping() {
        awaitInitialRefresh()
        compose.onNodeWithText("Playback target device ID").performScrollTo().performTextInput("dashboard-A")
        compose.onNodeWithText("Settings", useUnmergedTree=true).performClick()
        compose.onNodeWithText("HexPlayer API key").performTextInput("mock-only")
        compose.onNodeWithText("Cards", useUnmergedTree=true).performClick()
        compose.onNodeWithText("Tag UID (scan or enter manually)").performTextInput("04-AA-BB-CC")
        compose.onNodeWithText("Card name").performScrollTo().performTextInput("Kitchen tile")
        compose.onNodeWithText("Spotify URI").performScrollTo().performTextInput("spotify:track:abc123")
        compose.onNodeWithText("Playback target device ID").assertDoesNotExist()
        compose.onNodeWithText("Spotify device ID (required)").performScrollTo().performTextInput("mock-speaker")
    }
    @Test fun savedMappingReloadsIntoEditor() {
        enterMapping()
        compose.onNodeWithText("Save mapping").performScrollTo().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("Edit").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Clear editor").performScrollTo().performClick()
        compose.onNodeWithText("Edit").performScrollTo().performClick()
        compose.onNodeWithText("spotify:track:abc123").assertExists()
        compose.onNodeWithText("mock-speaker").assertExists()
        org.junit.Assert.assertEquals("mock-speaker", stored!!.getJSONObject("action").getString("device_id"))
        compose.onNodeWithText("Run saved action").performScrollTo().performClick()
        compose.waitUntil(10000) { triggeredTarget != null }
        org.junit.Assert.assertEquals("mock-speaker", triggeredTarget)
        compose.onNodeWithText("Player", useUnmergedTree=true).performClick()
        compose.onNodeWithText("dashboard-A").assertExists()
    }
    @Test fun malformedJsonBlocksSaveBeforeNetwork() {
        enterMapping()
        compose.onNodeWithText("HA event").performScrollTo().performClick()
        compose.onNodeWithText("Event type").performScrollTo().performTextInput("hexplayer_test")
        compose.onNodeWithText("Event data JSON").performScrollTo().performTextReplacement("not json")
        compose.onNodeWithText("Save mapping").performScrollTo().performClick()
        compose.onNodeWithText("Invalid JSON data:", substring=true).assertExists()
        org.junit.Assert.assertEquals(0, saveRequests)
    }
    @Test fun rotationPreservesInvalidJsonDraftAndTab() {
        enterMapping()
        compose.onNodeWithText("HA event").performScrollTo().performClick()
        compose.onNodeWithText("Event type").performScrollTo().performTextInput("hexplayer_test")
        compose.onNodeWithText("Event data JSON").performScrollTo().performTextReplacement("{invalid draft")
        compose.activityRule.scenario.recreate()
        compose.onNodeWithText("{invalid draft").assertExists()
        compose.onNodeWithText("hexplayer_test").assertExists()
        compose.onNodeWithText("Tag UID (scan or enter manually)").assertTextContains("04-AA-BB-CC")
        compose.onNodeWithText("Save mapping").performScrollTo().performClick()
        compose.onNodeWithText("Invalid JSON data:", substring=true).assertExists()
        org.junit.Assert.assertEquals(0, saveRequests)
    }
    @Test fun failedSaveShowsErrorAndKeepsDraft() {
        rejectSaves = true
        enterMapping()
        compose.onNodeWithText("Save mapping").performScrollTo().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("Save failed:", substring=true).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("spotify:track:abc123").assertExists()
        compose.onNodeWithText("Edit").assertDoesNotExist()
    }
}
