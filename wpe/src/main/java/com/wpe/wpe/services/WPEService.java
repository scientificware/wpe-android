/**
 * Copyright (C) 2022 Igalia S.L. <info@igalia.com>
 *   Author: Zan Dobersek <zdobersek@igalia.com>
 *   Author: Fernando Jimenez Moreno <fjimenez@igalia.com>
 *   Author: Loïc Le Page <llepage@igalia.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

package com.wpe.wpe.services;

import android.app.Service;
import android.content.Intent;
import android.os.Bundle;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import android.util.Log;

import androidx.annotation.NonNull;

import com.wpe.wpe.IWPEService;

public abstract class WPEService extends Service {
    private static final String LOGTAG = "WPEService";

    private final IWPEService.Stub binder = new IWPEService.Stub() {
        @Override
        public int connect(@NonNull Bundle args) {
            Log.v(LOGTAG, "IWPEService.Stub connect()");
            final ParcelFileDescriptor parcelFd = args.getParcelable("fd");

            new Thread(new Runnable() {
                @Override
                public void run() {
                    WPEService.this.initializeServiceMain(parcelFd);
                }
            }).start();

            return -1;
        }
    };

    protected static native void setupEnvironment(String[] envStringsArray);
    protected static native void initializeMain(int processType, int fd);

    protected abstract void loadNativeLibraries();
    protected abstract void setupServiceEnvironment();
    protected abstract void initializeServiceMain(@NonNull ParcelFileDescriptor parcelFd);

    @Override
    public void onCreate() {
        Log.i(LOGTAG, "onCreate()");
        super.onCreate();
        loadNativeLibraries();
        setupServiceEnvironment();
    }

    @Override
    public IBinder onBind(Intent intent) {
        Log.i(LOGTAG, "onBind()");
        return binder;
    }

    @Override
    public void onDestroy() {
        Log.i(LOGTAG, "onDestroy()");
        super.onDestroy();
    }
}
