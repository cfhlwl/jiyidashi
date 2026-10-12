package com.jiyidays.wxapi

import android.app.Activity
import android.os.Bundle
import com.jiyidays.BuildConfig
import com.jiyidays.WechatAuthCallbackRegistry
import com.jiyidays.WechatSdkAuthResponse
import com.tencent.mm.opensdk.constants.ConstantsAPI
import com.tencent.mm.opensdk.modelbase.BaseReq
import com.tencent.mm.opensdk.modelbase.BaseResp
import com.tencent.mm.opensdk.modelmsg.SendAuth
import com.tencent.mm.opensdk.openapi.IWXAPIEventHandler
import com.tencent.mm.opensdk.openapi.WXAPIFactory

/** Official WeChat callback owner; it forwards only a transient response. */
class WXEntryActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleCallback(intent)
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleCallback(intent)
    }

    private fun handleCallback(intent: android.content.Intent?) {
        val appId = BuildConfig.JIYI_WECHAT_APP_ID
        if (appId.isNullOrBlank() || intent == null) {
            finish()
            return
        }
        val api = WXAPIFactory.createWXAPI(this, appId, false)
        api.handleIntent(intent, object : IWXAPIEventHandler {
            override fun onReq(req: BaseReq) = Unit

            override fun onResp(resp: BaseResp) {
                if (resp.type != ConstantsAPI.COMMAND_SENDAUTH) return
                val authResp = resp as? SendAuth.Resp
                WechatAuthCallbackRegistry.dispatch(
                    WechatSdkAuthResponse(
                        errorCode = resp.errCode,
                        code = authResp?.code,
                        state = authResp?.state,
                    ),
                )
            }
        })
        finish()
    }
}
