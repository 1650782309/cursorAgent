/*
 * 从内存 dump 解密后的 global-metadata.dat。
 *
 * 适用场景：静态文件头部 magic 不是 AF 1B B1 FA（被加固/自定义加密）。
 * 原理：不管加密多复杂，il2cpp 运行时自己一定要拿到明文 metadata，
 *      等它初始化完成后在内存里搜 magic 头即可，比逆算法快一个数量级。
 *
 * 用法：frida -U -f <package> -l scripts/dump_metadata.js --no-pause
 * 产物：/data/local/tmp/global-metadata.dump.dat（需要设备可写该路径）
 */

const OUT_PATH = "/data/local/tmp/global-metadata.dump.dat";
const MAGIC = "af 1b b1 fa";
const MODULE = "libil2cpp.so";
// metadata 一般在几 MB 到上百 MB 之间，用来过滤误命中的 magic
const MIN_SIZE = 1 * 1024 * 1024;
const MAX_SIZE = 512 * 1024 * 1024;

function dumpAt(base, size) {
  const file = new File(OUT_PATH, "wb");
  const CHUNK = 1024 * 1024;
  let written = 0;
  while (written < size) {
    const n = Math.min(CHUNK, size - written);
    file.write(Memory.readByteArray(base.add(written), n));
    written += n;
  }
  file.flush();
  file.close();
  console.log(`[+] 已写出 ${written} 字节 -> ${OUT_PATH}`);
}

function guessSize(base) {
  /* metadata 头里 stringLiteralOffset 之后是一串 (offset,size) 对，
     最大的 offset+size 就是文件尾。这里粗略取头部所有 uint32 的最大值。 */
  let end = 0;
  for (let i = 8; i < 0x110; i += 4) {
    const v = base.add(i).readU32();
    if (v > end && v < MAX_SIZE) end = v;
  }
  return end > MIN_SIZE ? end : MIN_SIZE * 16;
}

function scan() {
  const mod = Process.findModuleByName(MODULE);
  if (mod === null) {
    console.log(`[-] 还没加载 ${MODULE}`);
    return false;
  }
  console.log(`[*] 在 ${mod.name} @ ${mod.base} (${mod.size}) 附近搜索 metadata`);

  // metadata 通常在堆上而不是 so 内部，所以扫可读可写的匿名映射
  const ranges = Process.enumerateRanges({ protection: "rw-", coalesce: true });
  for (const r of ranges) {
    if (r.size < MIN_SIZE) continue;
    let hits;
    try {
      hits = Memory.scanSync(r.base, Math.min(r.size, MAX_SIZE), MAGIC);
    } catch (e) {
      continue;
    }
    for (const hit of hits) {
      const version = hit.address.add(4).readU32();
      if (version < 16 || version > 40) continue; // metadata version 合理区间
      console.log(`[+] 命中 @ ${hit.address}，metadata version = ${version}`);
      dumpAt(hit.address, guessSize(hit.address));
      return true;
    }
  }
  console.log("[-] 未命中，游戏可能还没初始化完，稍后重试");
  return false;
}

/* il2cpp_init 返回后 metadata 一定已经解密并加载 */
function hookInit() {
  const init = Module.findExportByName(MODULE, "il2cpp_init");
  if (init === null) return false;
  Interceptor.attach(init, {
    onLeave() {
      console.log("[*] il2cpp_init 已返回，开始扫描");
      setTimeout(scan, 1500);
    },
  });
  console.log("[*] 已挂上 il2cpp_init");
  return true;
}

setImmediate(() => {
  if (!hookInit()) {
    // so 还没加载，等 dlopen
    const dlopen = Module.findExportByName(null, "android_dlopen_ext")
      || Module.findExportByName(null, "dlopen");
    Interceptor.attach(dlopen, {
      onEnter(args) {
        this.path = args[0].readCString();
      },
      onLeave() {
        if (this.path && this.path.indexOf(MODULE) !== -1) hookInit();
      },
    });
    console.log("[*] 等待 libil2cpp.so 加载");
  }
  // 兜底：直接手动触发 scan() 也可以
  rpc.exports = { scan };
});
