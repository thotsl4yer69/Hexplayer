package com.mazlabz.hexplayer.nfc

import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.Tag
import android.nfc.tech.Ndef
import com.mazlabz.hexplayer.model.UidCodec

object NfcTools {
    fun uid(tag: Tag): String = UidCodec.format(tag.id)
    fun read(tag: Tag): Result<String> = runCatching {
        val ndef = Ndef.get(tag) ?: error("Unsupported or unformatted tag: UID mapping is available, NDEF read/write is not. Use an NDEF-formatted tag.")
        ndef.connect()
        try {
            val content = ndef.ndefMessage?.records.orEmpty().joinToString("; ") {
                it.toUri()?.toString()?.let { uri -> uri + (NfcIdentity.labelWarning(uid(tag), uri)?.let { warning -> " · $warning" } ?: "") } ?: "NDEF record (${it.payload.size} bytes)"
            }.ifBlank { "Empty NDEF tag" }
            "$content · ${if (ndef.isWritable) "writable" else "locked / read-only"} · ${ndef.maxSize} bytes capacity"
        } finally { ndef.close() }
    }
    fun writeHexPlayerUri(tag: Tag, uid: String): Result<Unit> = runCatching {
        require(UidCodec.normalize(uid) == uid && uid(tag) == uid) { "Tag UID does not match the editor" }
        val message = NdefMessage(arrayOf(NdefRecord.createUri("hexplayer://card/$uid")))
        val ndef = Ndef.get(tag) ?: error("Unsupported or unformatted tag. Use an NDEF-formatted writable tag.")
        ndef.connect()
        try {
            VerifiedNdef.write(object : NdefPort {
                override val writable get() = ndef.isWritable
                override val capacity get() = ndef.maxSize
                override fun write(bytes: ByteArray) = ndef.writeNdefMessage(NdefMessage(bytes))
                override fun read(): ByteArray? = ndef.ndefMessage?.toByteArray()
            }, message.toByteArray())
        } finally { ndef.close() }
    }
}
