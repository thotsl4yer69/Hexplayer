package com.mazlabz.hexplayer.nfc

/** One physical operation per armed session. Cancellation invalidates late callbacks. */
class NfcSession {
    data class Operation(val generation: Long, val writeUid: String?)
    private var generation = 0L
    private var pending: Operation? = null
    @Synchronized fun arm(writeUid: String? = null) { pending = Operation(++generation, writeUid) }
    @Synchronized fun cancel() { generation++; pending = null }
    @Synchronized fun claim(uid: String): Operation? {
        val operation = pending ?: return null
        if (operation.writeUid != null && operation.writeUid != uid) return null
        pending = null
        return operation
    }
    @Synchronized fun isCurrent(operation: Operation): Boolean = generation == operation.generation
}
interface NdefPort {
    val writable: Boolean
    val capacity: Int
    fun write(bytes: ByteArray)
    fun read(): ByteArray?
}
object VerifiedNdef {
    fun write(port: NdefPort, payload: ByteArray) {
        require(port.writable) { "Tag is locked / read-only" }
        require(port.capacity >= payload.size) { "NDEF payload is too large for this tag" }
        port.write(payload)
        check(port.read()?.contentEquals(payload) == true) { "Read-back verification failed. Retap and read before retrying." }
    }
}

/** The immutable physical UID is authoritative; a writable URI cannot choose another card. */
object NfcIdentity {
    fun labelWarning(physicalUid: String, uri: String): String? {
        if (!uri.startsWith("hexplayer://card/", ignoreCase = true)) return null
        val labelUid = com.mazlabz.hexplayer.model.UidCodec.normalize(uri.substringAfterLast('/'))
        return if (labelUid != physicalUid) "Label UID differs from physical UID. Mapping uses physical UID $physicalUid; the label will not run another card." else null
    }
}
