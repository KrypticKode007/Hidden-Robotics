package com.kryptickode007.kai.bridge

import android.text.Html
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.Executors

/**
 * Android 15+ Cellular Micro-Tunnel Companion for Kai-007.
 *
 * Listens for incoming `web_fetch` or `web_search` JSON requests sent by macOS
 * over the 2.4 GHz BLE GATT link (`KaiBleBridgeService`), fetches the requested
 * content silently over Android's 5G/LTE cellular connection, strips HTML/ads
 * into compact plain text, and beams the result back over Bluetooth.
 */
object KaiBleWebTunnel {
    private const val TAG = "KaiBleWebTunnel"
    private const val MAX_RESPONSE_CHARS = 3500
    private val workerPool = Executors.newFixedThreadPool(2)

    /**
     * Entry point to call from `KaiBleBridgeService.handleMacCommand(rawJson)`.
     * Returns `true` if the JSON message was a web tunnel request and handled,
     * or `false` if it belongs to another command handler.
     */
    fun dispatchIfTunnelRequest(requestJson: JSONObject, sendReplyFn: (String) -> Unit): Boolean {
        val type = requestJson.optString("type", "")
        if (type != "web_fetch" && type != "web_search") {
            return false
        }
        handleRequestAsync(requestJson, sendReplyFn)
        return true
    }

    /**
     * Executes the HTTP/HTTPS request on a background worker thread and sends
     * the stripped plain-text payload back over BLE.
     */
    fun handleRequestAsync(requestJson: JSONObject, sendReplyFn: (String) -> Unit) {
        val reqId = requestJson.optString("req_id", "")
        val type = requestJson.optString("type", "web_fetch")

        val targetUrl = when (type) {
            "web_search" -> {
                val query = requestJson.optString("query", "").trim()
                if (query.isBlank()) return
                val encoded = URLEncoder.encode(query, "UTF-8")
                "https://lite.duckduckgo.com/lite/?q=$encoded"
            }
            else -> requestJson.optString("url", "").trim()
        }

        if (targetUrl.isBlank()) return

        workerPool.execute {
            val responseObj = JSONObject().apply {
                put("type", "web_fetch_result")
                put("req_id", reqId)
            }

            try {
                val cleanText = fetchAndStripHtml(targetUrl)
                responseObj.put("ok", true)
                responseObj.put("text", cleanText)
                Log.i(TAG, "Micro-tunnel fetched ${cleanText.length} chars for req_id=$reqId")
            } catch (e: Exception) {
                Log.w(TAG, "Micro-tunnel fetch failed for $targetUrl: ${e.message}")
                responseObj.put("ok", false)
                responseObj.put("error", e.message ?: "Cellular fetch failed")
            }

            sendReplyFn(responseObj.toString())
        }
    }

    private fun fetchAndStripHtml(urlString: String): String {
        var currentUrl = urlString
        var redirects = 0

        while (redirects < 4) {
            val conn = (URL(currentUrl).openConnection() as HttpURLConnection).apply {
                connectTimeout = 8000
                readTimeout = 8000
                instanceFollowRedirects = false
                setRequestProperty("User-Agent", "Kai007-MicroTunnel/1.0 (Android 15)")
                setRequestProperty("Accept", "text/html,application/xhtml+xml,text/plain;q=0.9")
            }

            val code = conn.responseCode
            if (code in 300..399) {
                val location = conn.getHeaderField("Location") ?: break
                currentUrl = URL(URL(currentUrl), location).toString()
                redirects++
                conn.disconnect()
                continue
            }

            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val rawBody = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            conn.disconnect()

            // Remove <script> and <style> blocks before HTML-to-text conversion
            val withoutScripts = rawBody
                .replace(Regex("(?is)<script.*?>.*?</script>"), " ")
                .replace(Regex("(?is)<style.*?>.*?</style>"), " ")

            val plainText = Html.fromHtml(withoutScripts, Html.FROM_HTML_MODE_COMPACT)
                .toString()
                .replace(Regex("\\s+"), " ")
                .trim()

            return plainText.take(MAX_RESPONSE_CHARS)
        }

        throw IllegalStateException("Too many HTTP redirects")
    }
}
