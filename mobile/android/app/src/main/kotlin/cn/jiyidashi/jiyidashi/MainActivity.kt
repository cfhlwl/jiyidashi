package cn.jiyidashi.jiyidashi

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Native location is registered explicitly rather than auto-started. Plugin
        // attachment only creates the bridge; permission and tracking remain user-driven.
        flutterEngine.plugins.add(NativeLocationPlugin())
    }
}
