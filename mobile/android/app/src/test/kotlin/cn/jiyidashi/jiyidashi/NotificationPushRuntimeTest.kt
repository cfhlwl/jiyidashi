package cn.jiyidashi.jiyidashi

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationPushRuntimeTest {
    @Test
    fun canonicalPayloadRejectsUnknownVersionAndArbitraryRoute() {
        assertNull(
            NotificationPushRuntime.parseCanonicalMessage(
                mapOf("version" to "2", "destination" to "HOME"),
            ),
        )

        val message =
            NotificationPushRuntime.parseCanonicalMessage(
                mapOf(
                    "version" to "1",
                    "destination" to "https://evil.example/",
                    "url" to "https://evil.example/",
                    "title" to "标题",
                    "body" to "正文",
                ),
            )
        requireNotNull(message)
        assertEquals("HOME", message.payload["destination"])
        assertTrue("url" !in message.payload)
    }

    @Test
    fun memoryRouteRequiresValidUuid() {
        val valid =
            NotificationPushRuntime.parseCanonicalMessage(
                mapOf(
                    "version" to "1",
                    "destination" to "MEMORY",
                    "resource_id" to "22222222-2222-4222-8222-222222222222",
                    "title" to "标题",
                    "body" to "正文",
                ),
            )
        requireNotNull(valid)
        assertEquals("MEMORY", valid.payload["destination"])

        val invalid =
            NotificationPushRuntime.parseCanonicalMessage(
                mapOf(
                    "version" to "1",
                    "destination" to "MEMORY",
                    "resource_id" to "not-a-uuid",
                ),
            )
        requireNotNull(invalid)
        assertEquals("HOME", invalid.payload["destination"])
        assertNull(invalid.payload["resource_id"])
    }
}
