package com.mazlabz.hexplayer.nfc

import android.net.Uri
import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.Tag
import android.nfc.tech.Ndef
import android.nfc.tech.NdefFormatable
import com.mazlabz.hexplayer.model.UidCodec

object NfcTools {
    fun uid(tag: Tag): String = UidCodec.format(tag.id)

    fun writeHexPlayerUri(tag: Tag, uid: String): Result<Unit> = runCatching {
        val message = NdefMessage(arrayOf(NdefRecord.createUri(Uri.parse("hexplayer://card/$uid"))))
        val ndef = Ndef.get(tag)
        if (ndef != null) {
            ndef.connect()
            try {
                require(ndef.isWritable) { "Tag is read-only" }
                require(ndef.maxSize >= message.toByteArray().size) { "NDEF payload is too large for this tag" }
                ndef.writeNdefMessage(message)
            } finally {
                ndef.close()
            }
            return@runCatching
        }

        val formatable = NdefFormatable.get(tag) ?: error("Tag does not support NDEF formatting")
        formatable.connect()
        try {
            formatable.format(message)
        } finally {
            formatable.close()
        }
    }
}
