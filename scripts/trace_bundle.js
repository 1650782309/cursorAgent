/*
 * 追踪 AssetBundle 加载，并把传给引擎的明文 bundle 落盘。
 *
 * 用途：
 *   1) 看清对方的资源加载策略（什么时候加载什么、同步还是异步、依赖顺序）
 *   2) bundle 自定义加密时，直接拿引擎收到的明文 —— 永远比逆解密算法快
 *
 * 用法：frida -U -f <package> -l scripts/trace_bundle.js --no-pause
 * 产物：/data/local/tmp/bundles/*.bin
 */

const OUT_DIR = "/data/local/tmp/bundles";
const MODULE = "libil2cpp.so";
const DUMP_MEMORY_BUNDLES = true;
const PRINT_BACKTRACE = false;

let n = 0;

/* --- il2cpp runtime API 的最小封装 --- */
const api = {};
function bind() {
  for (const name of [
    "il2cpp_domain_get", "il2cpp_domain_assembly_open", "il2cpp_assembly_get_image",
    "il2cpp_class_from_name", "il2cpp_class_get_method_from_name",
    "il2cpp_string_chars", "il2cpp_string_length", "il2cpp_array_length",
  ]) {
    const addr = Module.findExportByName(MODULE, name);
    if (addr === null) throw new Error(`找不到导出 ${name}`);
    api[name] = addr;
  }
  api.domain_get = new NativeFunction(api.il2cpp_domain_get, "pointer", []);
  api.assembly_open = new NativeFunction(api.il2cpp_domain_assembly_open, "pointer", ["pointer", "pointer"]);
  api.assembly_image = new NativeFunction(api.il2cpp_assembly_get_image, "pointer", ["pointer"]);
  api.class_from_name = new NativeFunction(api.il2cpp_class_from_name, "pointer", ["pointer", "pointer", "pointer"]);
  api.method_from_name = new NativeFunction(api.il2cpp_class_get_method_from_name, "pointer", ["pointer", "pointer", "int"]);
  api.string_chars = new NativeFunction(api.il2cpp_string_chars, "pointer", ["pointer"]);
  api.string_length = new NativeFunction(api.il2cpp_string_length, "int", ["pointer"]);
  api.array_length = new NativeFunction(api.il2cpp_array_length, "uint32", ["pointer"]);
}

function csString(ptr) {
  if (ptr.isNull()) return "<null>";
  try {
    return api.string_chars(ptr).readUtf16String(api.string_length(ptr));
  } catch (e) {
    return "<unreadable>";
  }
}

function resolve(assembly, ns, cls, method, argc) {
  const img = api.assembly_image(api.assembly_open(api.domain_get(), Memory.allocUtf8String(assembly)));
  const klass = api.class_from_name(img, Memory.allocUtf8String(ns), Memory.allocUtf8String(cls));
  if (klass.isNull()) return NULL;
  const m = api.method_from_name(klass, Memory.allocUtf8String(method), argc);
  return m.isNull() ? NULL : m.readPointer(); // Il2CppMethodPointer 在结构体首位
}

function dumpArray(arrPtr, tag) {
  // Il2CppArray: [header 0x10/0x20][length][...data]，64 位下数据从 +0x20 开始
  const len = api.array_length(arrPtr);
  if (len <= 0) return;
  const data = arrPtr.add(Process.pointerSize === 8 ? 0x20 : 0x10);
  const path = `${OUT_DIR}/${String(n++).padStart(4, "0")}_${tag}.bin`;
  const f = new File(path, "wb");
  f.write(Memory.readByteArray(data, len));
  f.flush();
  f.close();
  const head = data.readCString(8) || "";
  console.log(`[+] dump ${len} 字节 -> ${path}  head=${JSON.stringify(head.slice(0, 8))}`);
}

function hook(name, addr, onCall) {
  if (addr.isNull()) {
    console.log(`[-] 未解析到 ${name}`);
    return;
  }
  Interceptor.attach(addr, {
    onEnter(args) {
      onCall.call(this, args);
      if (PRINT_BACKTRACE) {
        console.log(Thread.backtrace(this.context, Backtracer.ACCURATE)
          .map(DebugSymbol.fromAddress).join("\n"));
      }
    },
  });
  console.log(`[*] 已挂 ${name} @ ${addr}`);
}

function install() {
  bind();
  const A = "UnityEngine.AssetBundleModule.dll";
  const NS = "UnityEngine";

  hook("AssetBundle.LoadFromFile", resolve(A, NS, "AssetBundle", "LoadFromFile_Internal", 3),
    function (args) { console.log(`[file] ${csString(args[0])}`); });

  hook("AssetBundle.LoadFromFileAsync", resolve(A, NS, "AssetBundle", "LoadFromFileAsync_Internal", 3),
    function (args) { console.log(`[file/async] ${csString(args[0])}`); });

  hook("AssetBundle.LoadFromMemory", resolve(A, NS, "AssetBundle", "LoadFromMemory_Internal", 2),
    function (args) {
      console.log("[memory] 收到 byte[]，这就是解密后的明文");
      if (DUMP_MEMORY_BUNDLES) dumpArray(args[0], "memory");
    });

  hook("AssetBundle.LoadFromMemoryAsync", resolve(A, NS, "AssetBundle", "LoadFromMemoryAsync_Internal", 2),
    function (args) {
      if (DUMP_MEMORY_BUNDLES) dumpArray(args[0], "memory_async");
    });

  hook("AssetBundle.LoadFromStream", resolve(A, NS, "AssetBundle", "LoadFromStreamInternal", 3),
    function () { console.log("[stream] 走 Stream 加载，需在 Stream.Read 层再抓"); });
}

setImmediate(() => {
  try {
    new File(`${OUT_DIR}/.keep`, "wb").close();
  } catch (e) {
    console.log(`[-] ${OUT_DIR} 不可写，先 mkdir 并放开权限`);
  }
  const tryInstall = () => {
    try {
      install();
      return true;
    } catch (e) {
      return false;
    }
  };
  if (!tryInstall()) {
    console.log("[*] il2cpp 尚未就绪，2 秒后重试");
    const timer = setInterval(() => {
      if (tryInstall()) clearInterval(timer);
    }, 2000);
  }
});
