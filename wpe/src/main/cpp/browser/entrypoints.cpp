#include "jnihelper.h"
#include "browser.h"
#include "logging.h"
#include "looperthread.h"
#include "pageeventobserver.h"
#include "environment.h"
#include "service.h"

#include <wpe/wpe.h>

extern "C" {
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*);
}

namespace {
jweak s_browserGlue_object = nullptr;

void setupEnvironment(JNIEnv*, jclass, jobjectArray envStringsArray)
{
    ALOGV("BrowserGlue::setupEnvironment() [tid %d]", gettid());
    wpe::android::pipeStdoutToLogcat();
    wpe::android::configureEnvironment(envStringsArray);
}

void init(JNIEnv* env, jclass, jobject glueObj)
{
    ALOGV("BrowserGlue::init(%p) [tid %d]", glueObj, gettid());

    if (s_browserGlue_object == nullptr)
        s_browserGlue_object = env->NewWeakGlobalRef(glueObj);

    Browser::getInstance().init();
}

void initLooperHelper(JNIEnv*, jclass)
{
    ALOGV("BrowserGlue::initLooperHelper() [tid %d]", gettid());

    LooperThread::initialize();
}

void shut(JNIEnv* env, jclass)
{
    ALOGV("BrowserGlue::shut() [tid %d]", gettid());

    Browser::getInstance().shut();

    if (s_browserGlue_object != nullptr) {
        env->DeleteWeakGlobalRef(s_browserGlue_object);
        s_browserGlue_object = nullptr;
    }
}

// Process management API

struct AndroidProcessProvider {
    struct wpe_process_provider *wpe_provider;
};

void* createProcessProvider(struct wpe_process_provider *process_provider)
{
    ALOGV("BrowserGlue createProcessProvider()");
    return new AndroidProcessProvider { process_provider };
}

void destroyProcessProvider(void* data)
{
    ALOGV("BrowserGlue destroyProcessProvider()");
    delete reinterpret_cast<AndroidProcessProvider*>(data);
}

int32_t launchProcess(void* data, enum wpe_process_type wpeProcessType, void* options)
{
    ALOGV("BrowserGlue launchProcess()");
    auto *provider = reinterpret_cast<AndroidProcessProvider*>(data);
    if (!provider)
        return -1;

    auto **argv = reinterpret_cast<char**>(options);
    if (!argv)
        return -1;

    uint64_t pid =  std::strtoll(argv[0], nullptr, 10);
    int32_t fd =  std::stoi(argv[1]);

    static auto processTypeToAndroidProcessType = [] (enum wpe_process_type wpeProcessType)
    {
        switch (wpeProcessType) {
        case WPE_PROCESS_TYPE_WEB:
            return wpe::android::ProcessType::WebProcess;
        case WPE_PROCESS_TYPE_NETWORK:
            return wpe::android::ProcessType::NetworkProcess;
        case WPE_PROCESS_TYPE_GPU:
        case WPE_PROCESS_TYPE_WEB_AUTHN:
        default:
            return wpe::android::ProcessType::TypesCount;
        }
    };

    auto processType = processTypeToAndroidProcessType(wpeProcessType);
    if (processType < wpe::android::ProcessType::FirstType || processType >= wpe::android::ProcessType::TypesCount) {
        ALOGE("Cannot launch process (invalid process type: %d)", static_cast<int>(processType));
        return -1;
    }

    ALOGV("BrowserGlue launchProcess - pid: %llu, processType: %d, fd: %d)", pid, static_cast<int>(processType), fd);

    try {
        JNIEnv* env = wpe::android::getCurrentThreadJNIEnv();
        if (!env->IsSameObject(s_browserGlue_object, nullptr)) {
            jobject obj = env->NewLocalRef(s_browserGlue_object);
            jclass klass = env->GetObjectClass(obj);

            jmethodID methodID = env->GetMethodID(klass, "launchProcess", "(JII)V");
            if (methodID != nullptr) {
                env->CallVoidMethod(obj, methodID, static_cast<jlong>(pid), static_cast<jint>(processType), fd);
                if (env->ExceptionCheck()) {
                    env->ExceptionDescribe();
                    env->ExceptionClear();
                    ALOGE("Cannot launch process (exception occurred on Java side)");
                }
            } else
                ALOGE("Cannot launch process (cannot find \"launchProcess\" method)");

            env->DeleteLocalRef(klass);
            env->DeleteLocalRef(obj);
        } else
            ALOGE("Cannot launch process (BrowserGlue has been garbage collected)");
    } catch (...) {
        ALOGE("Cannot launch process (JNI environment error)");
    }

    return 0;
}

void terminateProcess(void* data, int32_t pid)
{
    ALOGV("BrowserGlue terminateProcess()");
    auto *provider = reinterpret_cast<AndroidProcessProvider*>(data);
    if (!provider)
        return;

    uint64_t pid64 = pid;

    ALOGV("BrowserGlue terminateProcess - pid: %llu)", pid64);

    try {
        JNIEnv* env = wpe::android::getCurrentThreadJNIEnv();
        if (!env->IsSameObject(s_browserGlue_object, nullptr)) {
            jobject obj = env->NewLocalRef(s_browserGlue_object);
            jclass klass = env->GetObjectClass(obj);

            jmethodID methodID = env->GetMethodID(klass, "terminateProcess", "(J)V");
            if (methodID != nullptr) {
                env->CallVoidMethod(obj, methodID, static_cast<jlong>(pid64));
                if (env->ExceptionCheck()) {
                    env->ExceptionDescribe();
                    env->ExceptionClear();
                    ALOGE("Cannot terminate process (exception occurred on Java side)");
                }
            } else
                ALOGE("Cannot terminate process (cannot find \"terminateProcess\" method)");

            env->DeleteLocalRef(klass);
            env->DeleteLocalRef(obj);
        } else
            ALOGE("Cannot terminate process (BrowserGlue has been garbage collected)");
    } catch (...) {
        ALOGE("Cannot terminate process (JNI environment error)");
    }
}

struct wpe_process_provider_interface processProviderInterface = {
        .create = createProcessProvider,
        .destroy = destroyProcessProvider,
        .launch = launchProcess,
        .terminate = terminateProcess,
};

} // namespace

namespace wpe { namespace android {

extern int registerPage(JNIEnv*);

}} // namespace wpe::android

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved)
{
    JNIEnv* env = wpe::android::initVM(vm);
    jclass klass = env->FindClass("com/wpe/wpe/BrowserGlue");
    if (klass == nullptr)
        return JNI_ERR;

    static const JNINativeMethod methods[] = {
            { "setupEnvironment",          "([Ljava/lang/String;)V",                     reinterpret_cast<void*>(setupEnvironment) },
            { "init",                      "(Lcom/wpe/wpe/BrowserGlue;)V",               reinterpret_cast<void*>(init) },
            { "initLooperHelper",          "()V",                                        reinterpret_cast<void*>(initLooperHelper) },
            { "shut",                      "()V",                                        reinterpret_cast<void*>(shut) },
    };
    int result = env->RegisterNatives(klass, methods, sizeof(methods) / sizeof(JNINativeMethod));
    env->DeleteLocalRef(klass);

    struct JNIRegistrationMethod {
        const char* name;
        int (*func)(JNIEnv*);
    };

    static JNIRegistrationMethod registrationMethods[] = {
            { "Page", wpe::android::registerPage },
    };

    for (const auto &method : registrationMethods) {
        if (method.func(env) < 0) {
            ALOGE("%s registration failed!", method.name);
            return JNI_ERR;
        }
    }

    wpe_process_provider_register_interface(&processProviderInterface);

    return (result != JNI_OK) ? result : wpe::android::JNI_VERSION;
}
