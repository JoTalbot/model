package com.jotalbot.madworld

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.jotalbot.madworld.data.SharedPreferencesStore
import java.net.HttpURLConnection
import java.net.URI

class MadWorldFirebaseMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val session = SharedPreferencesStore(this, "player_session")
        val bearer = session.get("token") ?: return
        register(token, bearer)
    }

    override fun onMessageReceived(message: com.google.firebase.messaging.RemoteMessage) {
        // Data-only handling is intentionally left to the app's notification layer.
        // The service never logs payloads because they may contain player data.
    }

    private fun register(token: String, bearer: String) {
        runCatching {
            val connection = (URI.create("${BuildConfig.MADWORLD_API_URL}/api/v1/sessions/push-token").toURL().openConnection() as HttpURLConnection).apply {
                requestMethod = "PUT"
                connectTimeout = 10000
                readTimeout = 10000
                doOutput = true
                setRequestProperty("Authorization", "Bearer $bearer")
                setRequestProperty("Content-Type", "application/json")
            }
            val escaped = token.replace("\\", "\\\\").replace("\"", "\\\"")
            connection.outputStream.use { it.write("{\"token\":\"$escaped\",\"platform\":\"android\"}".toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            connection.disconnect()
            if (status !in 200..299) Log.w("MadWorldPush", "token registration rejected: HTTP $status")
        }.onFailure { Log.w("MadWorldPush", "token registration failed") }
    }
}
