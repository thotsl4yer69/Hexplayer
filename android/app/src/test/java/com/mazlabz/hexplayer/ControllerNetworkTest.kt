package com.mazlabz.hexplayer

import com.mazlabz.hexplayer.network.*
import com.mazlabz.hexplayer.model.*
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ControllerNetworkTest {
    private fun server(block: (HttpServer, String) -> Unit) {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.start()
        try { block(server, "http://127.0.0.1:${server.address.port}") } finally { server.stop(0) }
    }
    @Test fun saveReloadPreservesMappingAndBearer() = server { server, url ->
        var stored: JSONObject? = null
        server.createContext("/api/v1/cards") { exchange ->
            assertEquals("Bearer mock-only", exchange.requestHeaders.getFirst("Authorization"))
            val result = if (exchange.requestMethod == "PUT") {
                stored = JSONObject(exchange.requestBody.bufferedReader().readText()); "{}"
            } else JSONObject().put("cards", JSONObject().put("04-AA-BB-CC", stored)).toString()
            val bytes = result.toByteArray(); exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        val client = HexPlayerClient(url, "mock-only")
        val mapping = CardMapping("04-AA-BB-CC", "Kitchen", CardAction("ha_service", domain="automation", service="trigger", entityId="automation.kitchen"))
        client.upsert(mapping); assertEquals(listOf(mapping), client.cards())
    }
    @Test fun haArraySuccessIsNotReportedAsFailure() = server { server, url ->
        server.createContext("/api/services/media_player/media_stop") { exchange ->
            val bytes = "[]".toByteArray(); exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        HomeAssistantClient(url, "mock-only").service("media_player", "media_stop", JSONObject())
    }
    @Test fun serverErrorsPropagateWithoutSecretResponseBody() = server { server, url ->
        server.createContext("/api/v1/cards") { exchange ->
            val bytes = "secret-should-never-appear".toByteArray(); exchange.sendResponseHeaders(401, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        val error = assertThrows(java.io.IOException::class.java) { HexPlayerClient(url, "mock-only").cards() }
        assertTrue(error.message!!.contains("401")); assertFalse(error.message!!.contains("secret-should-never"))
    }
    @Test fun connectionFailureIsNotAnEmptySuccessfulList() {
        val socket = java.net.ServerSocket(0); val port = socket.localPort; socket.close()
        assertThrows(java.io.IOException::class.java) { HexPlayerClient("http://127.0.0.1:$port", "mock-only").cards() }
    }
}
