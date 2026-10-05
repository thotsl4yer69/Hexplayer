package com.mazlabz.hexplayer

import com.mazlabz.hexplayer.nfc.*
import com.mazlabz.hexplayer.model.*
import com.mazlabz.hexplayer.network.*
import org.junit.Assert.*
import org.junit.Test

class ControllerLogicTest {
    @Test fun repeatedScanIsConsumedOnce() {
        val session = NfcSession(); session.arm()
        assertNotNull(session.claim("04-AA")); assertNull(session.claim("04-AA"))
        session.arm(); assertNotNull(session.claim("04-AA"))
    }
    @Test fun cancellationInvalidatesQueuedResults() {
        val session = NfcSession(); session.arm(); val operation = session.claim("AA")!!
        session.cancel(); assertFalse(session.isCurrent(operation)); assertNull(session.claim("AA"))
    }
    @Test fun wrongTagCannotConsumeWrite() {
        val session = NfcSession(); session.arm("04-AA")
        assertNull(session.claim("04-BB")); assertNotNull(session.claim("04-AA"))
    }
    private class Port(override val writable: Boolean = true, override val capacity: Int = 100, val mismatch: Boolean = false) : NdefPort {
        var bytes: ByteArray? = null
        override fun write(bytes: ByteArray) { this.bytes = bytes }
        override fun read() = if (mismatch) byteArrayOf(9) else bytes
    }
    @Test fun writeRequiresFreshMatchingReadback() {
        val port = Port(); VerifiedNdef.write(port, byteArrayOf(1,2)); assertArrayEquals(byteArrayOf(1,2), port.bytes)
        assertThrows(IllegalStateException::class.java) { VerifiedNdef.write(Port(mismatch = true), byteArrayOf(1,2)) }
    }
    @Test fun lockedAndUndersizedTagsAreNeverWritten() {
        for (port in listOf(Port(writable=false), Port(capacity=1))) {
            assertThrows(IllegalArgumentException::class.java) { VerifiedNdef.write(port, byteArrayOf(1,2)) }
            assertNull(port.bytes)
        }
    }
    @Test fun uidNormalizationRejectsInvalidTags() {
        assertEquals("04-AA-FF-00", UidCodec.normalize("04:aa:ff:00"))
        for (value in listOf("", "1", "../bad", "GG", "04 XX", "04-AA", "00".repeat(11))) assertNull(UidCodec.normalize(value))
    }
    @Test fun credentialsCannotTravelOverLanHttp() {
        assertThrows(IllegalArgumentException::class.java) { TransportPolicy.validate("http://hexplayer.local:8787", true) }
        TransportPolicy.validate("https://hexplayer.example", true)
        TransportPolicy.validate("http://127.0.0.1:8787", true)
        assertThrows(IllegalArgumentException::class.java) { TransportPolicy.validate("https://user:secret@host", false) }
    }
    @Test fun allActionKindsRoundTrip() {
        val actions = listOf(
            CardAction("spotify", uri="spotify:track:123", deviceId="player"),
            CardAction("ha_media", entityId="media_player.kitchen", mediaContentId="radio"),
            CardAction("ha_service", domain="automation", service="trigger", entityId="automation.test", dataJson="{\"skip_condition\":false}"),
            CardAction("ha_event", eventType="hexplayer_card", dataJson="{\"room\":\"kitchen\"}")
        )
        actions.forEach { assertEquals(it, CardAction.fromJson(it.toJson())) }
    }
    @Test fun invalidActionDataIsNeverSilentlyDiscarded() {
        assertThrows(Exception::class.java) { CardAction("ha_event", eventType="test", dataJson="not json").toJson() }
    }
    @Test fun mutableUriCannotImpersonatePhysicalUid() {
        assertNotNull(NfcIdentity.labelWarning("04-AA-BB-CC", "hexplayer://card/04-11-22-33"))
        assertNotNull(NfcIdentity.labelWarning("04-AA-BB-CC", "hexplayer://card/not-a-uid"))
        assertNull(NfcIdentity.labelWarning("04-AA-BB-CC", "hexplayer://card/04-AA-BB-CC"))
    }
    @Test fun rearmedSessionRejectsPriorCallback() {
        val session = NfcSession(); session.arm(); val old = session.claim("04-AA-BB-CC")!!
        session.cancel(); session.arm()
        assertFalse(session.isCurrent(old)); assertTrue(session.isCurrent(session.claim("04-AA-BB-CC")!!))
    }
    @Test fun lostTagAfterWriteIsNotSuccessAndIsNotRetried() {
        var writes = 0
        val port = object : NdefPort {
            override val writable = true
            override val capacity = 100
            override fun write(bytes: ByteArray) { writes++ }
            override fun read(): ByteArray? = throw java.io.IOException("tag removed after write")
        }
        assertThrows(java.io.IOException::class.java) { VerifiedNdef.write(port, byteArrayOf(1,2)) }
        assertEquals(1, writes)
    }
}
