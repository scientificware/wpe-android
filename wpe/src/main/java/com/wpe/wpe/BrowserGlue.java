package com.wpe.wpe;

import android.util.Log;

import androidx.annotation.Keep;
import androidx.annotation.NonNull;
import androidx.annotation.UiThread;

@UiThread
public class BrowserGlue {
    private static final String LOGTAG = "BrowserGlue";

    private final Browser m_browser;

    static {
        System.loadLibrary("WPEBackend-default");
        System.loadLibrary("WPEBrowserGlue");
    }

    public static native void init(BrowserGlue self);
    public static native void deinit();

    public static native void newPage(Page page, int pageId, int width, int height);
    public static native void closePage(int pageId);

    public static native void loadURL(int pageId, String url);
    public static native void goBack(int pageId);
    public static native void goForward(int pageId);
    public static native void reload(int pageId);

    public static native void frameComplete(int pageId);

    public static native void touchEvent(int pageId, long time, int type, float x, float y);

    public BrowserGlue(@NonNull Browser browser) {
        m_browser = browser;
    }

    /**
     * This method is called directly from WebKit when a new auxiliary process needs to be created.
     * Given that Android forbids the fork syscall on non-rooted devices, we spawn Services to
     * host the logic of WebKit auxiliary processes.
     *
     * @param processType The type of service to launch. It can be a Web (0) or a Network (1) process.
     * @param pid The process identifier. This value is generated by WebKit and does not correspond with
     *            the actual system pid.
     * @param fds File descriptors used by WebKit for IPC.
     */
    @Keep
    public void launchProcess(long pid, int processType, @NonNull int[] fds) {
        Log.d(LOGTAG, "launchProcess " + pid);
        m_browser.launchAuxiliaryProcess(pid, processType, fds);
    }

    /**
     * Terminate the Service hosting the logic for a WebKit auxiliary process that matches the given pid
     *
     * @param pid The process identifier. This value is generated by WebKit and does not correspond with
     *            the actual system pid.
     */
    @Keep
    public void terminateProcess(long pid) {
        Log.d(LOGTAG, "terminateProcess " + pid);
        m_browser.terminateAuxiliaryProcess(pid);
    }

    @Keep
    public void loadProgress(double progress) {
        Log.d(LOGTAG, "progress " + progress);
    }
}
