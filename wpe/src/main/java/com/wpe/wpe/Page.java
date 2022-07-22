package com.wpe.wpe;

import android.content.Context;
import android.content.Intent;
import android.os.ParcelFileDescriptor;
import android.util.Log;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.inputmethod.InputMethodManager;

import androidx.annotation.Keep;
import androidx.annotation.NonNull;
import androidx.annotation.UiThread;
import androidx.annotation.WorkerThread;

import com.wpe.wpe.services.WPEServiceConnection;
import com.wpe.wpeview.WPEView;

/**
 * A Page roughly corresponds with a tab in a regular browser UI.
 * There is a 1:1 relationship between WPEView and Page.
 * Each Page instance has its own wpe.wpe.gfx.View and WebKitWebView instances associated.
 * It also keeps references to the Services that host the logic of WebKit's auxiliary
 * processes (WebProcess and NetworkProcess).
 */
@UiThread
public class Page
{
    private final String LOGTAG;

    static public final int LOAD_STARTED = 0;
    static public final int LOAD_REDIRECTED = 1;
    static public final int LOAD_COMMITTED = 2;
    static public final int LOAD_FINISHED = 3;

    private final int m_id;

    private final Browser m_browser;
    private final Context m_context;
    private final WPEView m_wpeView;

    private boolean m_closed = false;

    private final int m_width;
    private final int m_height;

    private PageSurfaceView m_surfaceView;

    private boolean m_canGoBack = true;
    private boolean m_canGoForward = true;

    private ScaleGestureDetector m_scaleDetector;
    private boolean m_ignoreTouchEvent = false;

    private long m_nativePtr;
    private native void nativeInit(int pageId, int width, int height);
    private native void nativeClose();
    private native void nativeDestroy();
    private native void nativeLoadUrl(String url);
    private native void nativeGoBack();
    private native void nativeGoForward();
    private native void nativeStopLoading();
    private native void nativeReload();

    private native void nativeSurfaceCreated(Surface surface);
    private native void nativeSurfaceDestroyed();
    private native void nativeSurfaceChanged(int format, int width, int height);
    private native void nativeSurfaceRedrawNeeded();

    private native void nativeSetZoomLevel(double zoomLevel);

    private native void nativeOnTouchEvent(long time, int type, float x, float y);

    private native void nativeSetInputMethodContent(char c);
    private native void nativeDeleteInputMethodContent(int offset);

    private native void nativeRequestExitFullscreenMode();

    private native void nativeUpdateAllSettings(PageSettings settings);

    private class PageSurfaceHolderCallback implements SurfaceHolder.Callback2
    {
        @Override
        public void surfaceCreated(SurfaceHolder holder)
        {
            Log.d(LOGTAG, "PageSurfaceHolderCallback::surfaceCreated()");
            nativeSurfaceCreated(holder.getSurface());
        }

        @Override
        public void surfaceDestroyed(SurfaceHolder holder)
        {
            Log.d(LOGTAG, "PageSurfaceHolderCallback::surfaceDestroyed()");
            nativeSurfaceDestroyed();
        }

        @Override
        public void surfaceChanged(SurfaceHolder holder, int format, int width, int height)
        {
            Log.d(LOGTAG, "PageSurfaceHolderCallback::surfaceChanged() format " + format + " (" + width + "," + height + ")");

            nativeSurfaceChanged(format, width, height);
        }

        @Override
        public void surfaceRedrawNeeded(SurfaceHolder holder)
        {
            Log.d(LOGTAG, "PageSurfaceHolderCallback::surfaceRedrawNeeded()");
            nativeSurfaceRedrawNeeded();
        }
    }

    private class PageScaleListener extends ScaleGestureDetector.SimpleOnScaleGestureListener
    {
        private float m_scaleFactor = 1.f;

        @Override
        public boolean onScale(ScaleGestureDetector detector)
        {
            Log.d(LOGTAG, "PageScaleListener::onScale()");

            m_scaleFactor *= detector.getScaleFactor();

            m_scaleFactor = Math.max(0.1f, Math.min(m_scaleFactor, 5.0f));

            nativeSetZoomLevel(m_scaleFactor);

            m_ignoreTouchEvent = true;

            return true;
        }
    }

    public class PageSurfaceView extends SurfaceView
    {
        public PageSurfaceView(Context context)
        {
            super(context);
        }

        @Override
        public boolean onTouchEvent(MotionEvent event)
        {
            int pointerCount = event.getPointerCount();
            if (pointerCount < 1) {
                return false;
            }

            m_scaleDetector.onTouchEvent(event);

            if (m_ignoreTouchEvent) {
                m_ignoreTouchEvent = false;
            }

            int eventType;

            int eventAction = event.getActionMasked();
            switch (eventAction) {
            case MotionEvent.ACTION_DOWN:
                eventType = 0;
                break;
            case MotionEvent.ACTION_MOVE:
                eventType = 1;
                break;
            case MotionEvent.ACTION_UP:
                eventType = 2;
                break;
            default:
                return false;
            }

            nativeOnTouchEvent(event.getEventTime(), eventType, event.getX(0), event.getY(0));
            return true;
        }
    }

    public Page(@NonNull Browser browser, @NonNull Context context, @NonNull WPEView wpeView, int pageId)
    {
        LOGTAG = "WPE page" + pageId;

        Log.v(LOGTAG, "Page construction " + this);

        m_id = pageId;

        m_browser = browser;
        m_context = context;
        m_wpeView = wpeView;

        m_width = wpeView.getMeasuredWidth();
        m_height = wpeView.getMeasuredHeight();

        m_surfaceView = new PageSurfaceView(m_context);
        if (m_wpeView.getSurfaceClient() != null) {
            m_wpeView.getSurfaceClient().addCallback(wpeView, new PageSurfaceHolderCallback());
        } else {
            SurfaceHolder holder = m_surfaceView.getHolder();
            Log.d(LOGTAG, "Page surface holder " + holder);
            holder.addCallback(new PageSurfaceHolderCallback());
        }
        m_surfaceView.requestLayout();

        m_scaleDetector = new ScaleGestureDetector(context, new PageScaleListener());
    }

    public void init()
    {
        nativeInit(m_id, m_width, m_height);

        m_wpeView.onPageSurfaceViewCreated(m_surfaceView);
        m_wpeView.onPageSurfaceViewReady(m_surfaceView);

        updateAllSettings();
        m_wpeView.getSettings().getPageSettings().setPage(this);
    }

    public void close()
    {
        if (m_closed) {
            return;
        }
        m_closed = true;
        Log.v(LOGTAG, "Page destruction");
        nativeClose();
    }

    public void destroy()
    {
        close();
        nativeDestroy();
    }

    @Override
    protected void finalize() throws Throwable {
        try {
            destroy();
        } finally {
            super.finalize();
        }
    }

    @WorkerThread
    public WPEServiceConnection launchService(@NonNull ProcessType processType, @NonNull ParcelFileDescriptor parcelFd, @NonNull Class<?> serviceClass)
    {
        Log.v(LOGTAG, "launchService type: " + processType.name());
        Intent intent = new Intent(m_context, serviceClass);

        WPEServiceConnection serviceConnection = new WPEServiceConnection(processType, this, parcelFd);
        switch (processType) {
        case WebProcess:
            // FIXME: we probably want to kill the current web process here if any exists when PSON is enabled.
            m_browser.setWebProcess(serviceConnection);
            break;

        case NetworkProcess:
            m_browser.setNetworkProcess(serviceConnection);
            break;

        default:
            throw new IllegalArgumentException("Unknown process type");
        }

        m_context.bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE | Context.BIND_IMPORTANT);
        return serviceConnection;
    }

    @WorkerThread
    public void stopService(@NonNull WPEServiceConnection serviceConnection)
    {
        Log.v(LOGTAG, "stopService type: " + serviceConnection.getProcessType().name());
        // FIXME: Until we fully support PSON, we won't do anything here.
    }

    public void loadUrl(@NonNull Context context, @NonNull String url)
    {
        Log.d(LOGTAG, "loadUrl " + url);
        nativeLoadUrl(url);
    }

    public void onLoadChanged(int loadEvent)
    {
        m_wpeView.onLoadChanged(loadEvent);
        if (loadEvent == Page.LOAD_STARTED) {
            dismissKeyboard();
        }
    }

    public void onLoadProgress(double progress)
    {
        m_wpeView.onLoadProgress(progress);
    }

    public void onUriChanged(String uri)
    {
        m_wpeView.onUriChanged(uri);
    }

    public void onTitleChanged(String title, boolean canGoBack, boolean canGoForward)
    {
        m_canGoBack = canGoBack;
        m_canGoForward = canGoForward;
        m_wpeView.onTitleChanged(title);
    }

    public void onInputMethodContextIn()
    {
        InputMethodManager imm = (InputMethodManager)m_context.getSystemService(Context.INPUT_METHOD_SERVICE);
        imm.toggleSoftInput(InputMethodManager.SHOW_FORCED, 0);
    }

    private void dismissKeyboard()
    {
        InputMethodManager imm = (InputMethodManager)m_context.getSystemService(Context.INPUT_METHOD_SERVICE);
        imm.hideSoftInputFromWindow(m_surfaceView.getWindowToken(), 0);
    }

    public void onInputMethodContextOut()
    {
        dismissKeyboard();
    }

    public void enterFullscreenMode()
    {
        Log.v(LOGTAG, "enterFullscreenMode");
        m_wpeView.enterFullScreen();
    }

    public void exitFullscreenMode()
    {
        Log.v(LOGTAG, "exitFullscreenMode");
        m_wpeView.exitFullScreen();
    }

    public void requestExitFullscreenMode()
    {
        nativeRequestExitFullscreenMode();
    }

    public boolean canGoBack()
    {
        return m_canGoBack;
    }

    public boolean canGoForward()
    {
        return m_canGoForward;
    }

    public void goBack()
    {
        nativeGoBack();
    }

    public void goForward()
    {
        nativeGoForward();
    }

    public void stopLoading()
    {
        nativeStopLoading();
    }

    public void reload()
    {
        nativeReload();
    }

    public void setInputMethodContent(char c)
    {
        nativeSetInputMethodContent(c);
    }

    public void deleteInputMethodContent(int offset)
    {
        nativeDeleteInputMethodContent(offset);
    }

    void updateAllSettings()
    {
        nativeUpdateAllSettings(m_wpeView.getSettings().getPageSettings());
    }
}
