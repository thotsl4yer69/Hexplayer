package com.mazlabz.hexplayer

import com.mazlabz.hexplayer.model.UidCodec
import org.junit.Assert.assertEquals
import org.junit.Test

class NfcUidTest {
    @Test fun formatsUnsignedUidBytes() {
        assertEquals("04-A1-00-FF", UidCodec.format(byteArrayOf(0x04, 0xA1.toByte(), 0x00, 0xFF.toByte())))
    }
}
