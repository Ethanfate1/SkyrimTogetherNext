# 更新日志

本项目的更新记录以 **GitHub Releases** 为准:

> https://github.com/komAAmok/SkyrimTogetherNext/releases

每个 tag(形如 `v1.0.20`)对应一个 Release,附上版本号相同的两个包——
客户端 mod 与专用服务器。逐条提交的历史见 `git log` 与各次 PR。

## v1.1.6(2026-09-27)

### 修复:两处「刚进游戏就闪退」—— 一处在我们的运行时,一处在 RaceMenu 接口版本

**现象**:MO2 + SKSE 打开游戏「一小会儿就直接闪退」。日志里三种崩溃,其中两种反复出现,
都是 `EXCEPTION_ACCESS_VIOLATION`,而且两次读到的都是 `0x14`
(即 `TESForm::formID` 的偏移)附近那个**不可能是地址**的数:

```
# A（三次）skee64.dll+0x81be8                  mov eax, [r14+0x14]   target 0x15
# B（一次）  SkyrimTogetherRuntime_1_5.dll+0x16CFA8  mov eax, [r15+0x14]   target 0x14
```

**A:RaceMenu 的接口按名字取,布局没人核对。** 插件发 `kMessageExchangeInterface` 拿到
`IInterfaceMap`,再 `QueryInterface("Overlay")` —— 这一步**只按名字查表,不校验布局**。
实测本机的 `skee64.dll` 里 `.?AVOverlayInterface@@` 的 vtable 是**版本 1**(23 槽),
而两个插件声明的是**版本 2**:插件以为槽位 `[11]` 是 `GetOverlayCount`,
DLL 那里其实是 `RevertHeadOverlays`。于是 `GetOverlayCount(Spell, ...)` 把
`rdx = 1`(枚举值 `OverlayType::Spell`)当成 `TESObjectREFR*` 传进去,
读 `[1+0x14]` = `0x15` → 闪退。

这也解释了**为什么能进游戏**:四次 `Normal` 调用的 `rdx = 0`,
而 v1 的 `RevertHeadOverlays` 开头恰好有 `testq %rdx,%rdx; je`,
所以它们**全部安全返回**;只有 `Spell` 才踩中 —— 正是「玩一小会儿才崩」。

**修法**:两个插件(补丁形式,见 `Code/plugins/patches/`)在采用接口前**先查 `GetVersion()`**,
版本不足就拒绝该接口并打印明确错误,而不是继续调用。`GetVersion()` 在每种布局里都是槽位 `[1]`,
是唯一能在调用其它方法之前安全调用的方法。`IBodyMorphInterface` 只追加,所以版本 4 的声明对版本 5 仍有效,
门禁写成 `>= 4` 而非 `== 5`。

**B:引擎用空指针调用装备钩子来清空槽位。** `Code/client/Games/Skyrim/EquipManager.cpp` 的六个钩子里,
只有 `apActor` 判了空。法术/龙吼四个直接读 `apSpell->formID` / `apShout->formID`,
而**引擎清空一只手时就是用空形式调用它们**的 → 读 `[0+0x14]` → 闪退。
(物品那两个钩子的 `pSlot` 早就写了 `?: 0` 三元写法,说明这个坑当时知道,只是没推广过去。)

**修法**:六个钩子统一判空,且为空时**原样转发给原函数**而不是返回 `nullptr`
(返回 `nullptr` 会让引擎以为「这次装备被取消」,与清空槽位的行为不符);
`pEquipSlot` 同样补上 `?: 0`。

### 新增门禁:SKEE 接口声明的顺序与版本

新增 `Code/plugins/tools/check_skee_abi.py`(已接入 `plugins.yml`):
把两个插件声明的 SKEE 方法**顺序**逐槽与 RaceMenu 的真实顺序比对,并要求每份声明都带
版本门禁。**反向验证过三种改坏方式**,每一种都会被它抓到:删掉 `RevertOverlay`、
对调 `GetOverlayCount`/`GetOverlayFormat`、移除版本门禁。

> 详细取证(反汇编、`target address` 的读法、两个布局的逐槽对照)见 `docs/PITFALLS.md` §37。

### 修复:自定义种族的头不显示(任何「头不是本机生成的」角色)

**现象**:用**自带头部 `.nif`/`.tri` 的自定义种族**时,头是**隐形**的 ——
没有用 RaceMenu 雕刻、没有套预设、没有动任何滑块,只是把种族自带的头部网格直接用上。
报告者补了一条关键线索:**同一套自定义头部网格配原版种族是正常显示的**
(Nolvus v6 给原版种族换的就是 HPH High Poly Head + Expressive Facegen),
而这一切在 **STR 1.7.1.42 上都是好的**。所以既不是 `.nif`/`.tri` 本身的问题,也不只是「自定义种族」四个字,
而是**「这张脸不是在本机生成的」**。

**根因:上游 #764 删掉了「强制运行时生成脸」那一行。**

引擎用 `bUseFaceGenPreprocessedHeads`(默认 **1**)决定角色的头从哪来:
从磁盘上预先烘焙好的 `Data\meshes\actors\character\FaceGenData\FaceGeom\<插件>\<formid>.nif` 加载,
还是**当场生成**。远端玩家的外观是**序列化后传过来、在本机重建**的,
它描述的那张脸**从没在本机生成过**,所以磁盘上**不存在**匹配的烘焙网格 ——
引擎照默认路径去找、找不到,头就是空的。

自定义种族踩得最狠,因为**它的头只以种族自带的 `.nif`/`.tri` 形式存在,从来没有 FaceGenData**;
而原版种族即使换了自定义头部网格,那些烘焙资源仍然对得上,所以「原版种族 + 自定义头」正常 ——
这正是报告里「vanilla races with custom head meshes work fine」的由来。

1.7.1 之所以是好的,是因为它**每帧**都在执行:

```cpp
// Every frame make sure we won't use preprocessed facegen
POINTER_SKYRIMSE(uint32_t, bUseFaceGenPreprocessedHeads, 378620);
*bUseFaceGenPreprocessedHeads = 0;
```

上游 PR #764(`7e09f8b4`,`Now respects bUseFaceGenPreprocessedHeads flag.`)把这行删了,
为的是修**原版角色**的脖子接缝、黑脸与头部错配(v1.8.0 发布说明:
`Re-enabled bUseFaceGenPreprocessedHeads; this fixes occasional mismatched heads,
face discoloration and facegen mods`)。
**本仓库每个 1.1.x 都含这个删除,而报告者说好的 1.7.1 不含** —— 版本边界与报告完全吻合
(`git merge-base --is-ancestor 7e09f8b4` 对 v1.1.0/1.1.1/1.1.5/HEAD 为真,对 v1.7.1 为假)。

仓库里其实**一直躺着一个专为此写的函数**:`Code/client/Games/Skyrim/Actor.cpp` 的
`Actor::QueueUpdate()` —— 它把该 INI 置 0、调用引擎的 Actor 更新、再把值放回去,
正是「按需强制一次运行时生成」。但它**从未被任何调用点引用**
(1.0.x 到 1.8.x、以及上游 master/dev 全部 ref 都 grep 过,只有它自己的定义),
因为当年走的是「每帧全局清零」那条路。

**修法:把「清零」收窄到真正需要它的角色上。**

`CharacterService` 新增一个**窗口**:

- `SetRemoteFaceGenForce(true)` 在**两个**「外观来自网络」的生成路径上、
  **在把 actor 交给引擎之前**调用(引擎要到**下一帧**才建身体,晚一步就晚了);
- 它先把**当前值存下来**,关窗时**存回原值**,不写死成 1 ——
  这个设置不是我们拥有的,玩家自己关过就得保持关着;
- `UpdateRemoteFaceGenWindow()` **每帧**从 `WaitingFor3D` 推导窗口该不该开:
  只看 `FormId == GameId{}`(即 base 是**在本机从缓冲区重建**的)那些角色。
  用「推导」而不是「配对开关」是故意的 —— 断线、生成失败、角色被删都会自动掉出这个视图,
  不需要谁记得去关,与它下面那个早就在等同一个组件的 `RunSpawnUpdates` 一致。

于是**两边都满足**:本机生成的角色(玩家的,以及所有磁盘上就有烘焙头的 NPC)
继续走 #764 想要的预处理路径,脖子接缝那个修复不被回退;
只有**头从网络来**的角色改用运行时生成 —— 也就是那些隐形的头。

### 新增门禁:预处理头部开关的作用域

新增 `Tools/Scripts/check_facegen_scope.py`(读源码前**先剥注释**),查五件事:

1. **全局清零不准回来** —— 它正是 #764 回退掉的东西,
   在 `TiltedOnlineApp.cpp` 里重新加回会被抓(那里长的注释里提到该设置不算);
2. **每个写这个开关的地方都必须「先存后还原」** —— 包括那个没被调用的 `Actor::QueueUpdate()`,
   它是个正确的存/还原,门禁要求它保持正确;
3. **窗口必须按「来自网络」定界**(等 3D + 空的 FormId),否则不是恒开就是恒关;
4. **窗口必须在 `Actor::Create` 之前打开** —— 身体是后面那一帧才建的;
5. **每帧必须关窗**,以及**取 INI 前必须判空**。

**反向验证过十种改坏方式**,每一种都被抓到:重新加回全局清零;
两处生成路径各自把开窗挪到 `Actor::Create` 之后;去掉每帧关窗;
把窗口放大成「所有等待中的角色」;把 `FormId` 比较反过来;
从视图里去掉 `RemoteComponent`;去掉 INI 判空;两个「先存后还原」各丢掉一次还原。

> 其中「把 `FormId` 比较反过来」**最初逃过了第一版门禁** —— 那一版只查标记是否存在、
> 不查它是不是那个比较,已改成用正则校验比较本身。改坏方式能被自己写的门禁漏掉,
> 只有真去改一遍才会发现。

> 详细取证(上游 #764 的完整正文、`merge-base --is-ancestor` 逐个 tag 的版本边界、
> 以及为什么 tint 纹理那条路不是原因)见 `docs/PITFALLS.md` §38。
## v1.1.5(2026-09-27)

### 文档约定:已修的缺陷不再写进 README

两个 README 里那节「曾经误报为冲突、现已兼容:KiLoader / KreatE」**已删除**,
同时把这条约定写进 `CODE_GUIDELINES.md`(新增「Where a fix is explained, and
where it is not」一节),以后照此办理。

**为什么删**:README 回答的是「装哪个版本、什么能用、出问题怎么办」。
一个**已经修好**的缺陷不属于这三者 —— 修复出货之后读者没有任何可做的动作,
于是那一段只会被读一次,然后永久占着位置,把玩家真正要看的内容越推越远;
更糟的是它会**过时成一段关于没人再跑的构建的描述**。

**以后放哪里**:

| 内容 | 去处 |
| --- | --- |
| 缺陷已修(包括被广泛误报的、用户点名问过的) | `CHANGELOG.md`;细节值得留就进 `docs/PITFALLS.md` |
| 玩家必须**动手**的变化 | README:要装的版本、支持的游戏版本、**仍然存在**的冲突、安装步骤、该看的日志 |
| 已修缺陷在 README 的痕迹 | 至多版本表里一行 |
| 「不要启用这个 Mod」清单 | 只列**仍然冲突**的;修好就删掉,不留作历史 |

**判据**(写之前先问):*这个修复出货之后,读者会因此做什么不一样的事?*
答案是「没有」,就写进 CHANGELOG,不写进 README。

> 顺带把 1.1.5 那一行从「修复叙事」压回一行摘要:版本表是索引,不是事故报告。
### 修复:插件补丁里的 fmt 占位符写错,导致 CI 编译失败

**现象**:`Build windows` 与 `Playable Skyrim Together Build` 两个工作流都红,
标注为 `companion plugin build failed: DAVSyncTogether (build)`,编译错误是
`DAVConfigIndex.cpp(109,17): error C7595: 'fmt::v12::fstring<...>::fstring': call to
immediate function is not a constant expression`。

**根因**:错在**本仓库自己的补丁文件**,不在插件源码里。
`Code/plugins/patches/DAVSyncTogether/0001-config-index-enumeration.patch` 里那两条
日志的占位符写成了 `path=\"{\"} \" error=\"{\"}` —— **转义引号写进了花括号里面**。
C++ 编译器看到的是 `path="{"} " error="{"}`;`fmt` 在**编译期**解析格式串时,
把花括号里的 `"` 当成**格式说明符**,而 `std::string` 没有对应它的 formatter,
于是直接编译失败。写成 `path=\"{}\" error=\"{}\"` 即两个正常占位符,问题消失。

**为什么 CI 挡不住、本地也看不见**:

- `git apply` 只看补丁**能不能打上**。这条补丁语法完全正确、上下文完全匹配,
  `PATCH VERIFY OK` 一路绿灯 —— 它根本不知道打进去的 C++ 编不过;
- 本地没有 Windows SDK 与 vcpkg,`fmt` 的编译期检查跑不起来,
  所以这个错误**只在 Windows 构建里、十几分钟之后**才现身。

**修法**:补丁里两行占位符改回 `\"{}\"`。**补丁语义一字未动**,
只是把转义引号移到花括号外面;`git diff` 恰好 2 行。

**顺带加了一条门禁**(`Code/plugins/tools/plugin_patches.py`):`verify` 与 `check`
现在会**逐行扫补丁的新增行**,凡是花括号里出现引号的占位符一律报错,并直接指出
正确写法。规则刻意收得很窄 —— 真正的格式说明符是宽度/精度/类型字母,
引号出现在里面**必然是转义写错了**,所以不会误伤合法写法。反向验证过:
把补丁改回原来的写法,门禁立刻报出两处(第 25、34 行)。

> **教训**:补丁能应用 ≠ 补丁编得过。`git apply` 的绿灯只证明文本能对上,
而**唯一的真值来源是编译器**。这类「本地绿、远端红」的坑,
要么在本地补齐工具链,要么把判据写成门禁 —— 这次选了后者,
因为它是**可判定**的:花括号里不该有引号。

### 修复:KiLoader / KreatE 的「不兼容」弹窗(它们本来并不冲突)

**现象**:装了 KiLoader(以及依赖它的 KreatE / AELAS)之后,启动游戏弹
`KiLoader initialization failed`,细节是两条 `Couldn't open logging file`,
第二条 `std::system_error: The process cannot access the file because it is being
used by another process`。看起来像本框架与 KiLoader 不兼容,上游也有同样的
报告([TiltedEvolution#766](https://github.com/tiltedphoques/TiltedEvolution/issues/766),
至今 open,回复是「无法承诺支持 KiLoader」)。

**根因**(证据来自报错文本本身,不是推测):

1. 报错里的进程名是 **`KiLoaderTPProcess`** —— 那是**本框架的 CEF 辅助进程**
   `TPProcess.exe` 的名字,不是游戏进程。也就是说 KiLoader 是在**我们的辅助进程里**
   被拉起来的;
2. 为什么会被拉起来:`TPProcess.exe` 位于**游戏根目录**,Windows 解析它的导入表时
   **先搜 exe 所在目录**,再搜 `System32`;而 `libcef.dll` 按名字延迟加载
   `dxgi.dll`、`d3d11.dll`、`d3d12.dll`、`dcomp.dll`(自写 PE 解析读延迟导入表确认)。
   这四个正是 ENB、ReShade、SpecialK、Community Shaders 用来挂代理的名字,于是
   辅助进程加载的是**游戏根目录的 ENB 代理**,ENB 再带起 `enbseries\` 下的卫星 DLL,
   `KiLoaderSatelliteENB` 随之拉起一份 KiLoader;
3. 为什么那一份必死:KiLoader 的日志路径按**当前进程名**推导,于是它去开
   `Data\KiLoader\KiLoader.log` —— 而游戏进程**整场**都占着这个文件
   (报错第一行的 `AppData\Local\KiLoaderTPProcess\Logs\KiLoader.log` 同样来自
   进程名)。同一个框架的两份实例无法共用该文件,第二份在启动阶段即失败。

所以这**不是**功能冲突,而是辅助进程误加载了不属于它的 DLL,再由 KiLoader 如实报出
了这个碰撞。

**修法**:`Code/tp_process/main.cpp` 在 `CefExecuteProcess` 之前,按**完整路径**加载
`System32` 的 `dxgi.dll`、`d3d11.dll`、`d3d12.dll`、`dcomp.dll` —— 这四个既是
`libcef.dll` **延迟导入表**里的名字(直接读 PE 得到,其余延迟导入都是 USER32/SHELL32
这类不可能被 mod 占用的系统名),也正是图形框架会占用的代理名。加载器在搜索任何目录
之前会先按**基名**匹配已加载模块,因此随后的按名加载(延迟导入正是按名)直接命中它们,
不再落到游戏根目录。

两个细节是**实测**出来的,不是照抄:

- **顺序必须 `dxgi` 在前**:`System32\d3d11.dll` 静态导入 `dxgi.dll`,先加载 `d3d11`
  会让它自己的依赖解析到游戏根目录的代理,加载失败并报 `ERROR_BAD_EXE_FORMAT (193)`。
  本机用一份同名的假代理复现:先 `d3d11` → 193;先 `dxgi` → 两者都正确落到 `System32`。
  (`d3d12.dll` / `dcomp.dll` **不**导入 `dxgi`,这点也实测过,所以只有前两个的相对顺序
  是硬要求);
- **不能改用 `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)`**:本框架自己的
  overlay 运行时(`libEGL.dll`、`libGLESv2.dll`、`vk_swiftshader.dll`、
  `d3dcompiler_47.dll`)同样部署在游戏根目录并**按名**加载,收紧搜索路径会把
  「辅助进程误加载 ENB」换成「overlay 起不来」。只钉这四个名字即可,
  因为 `libcef.dll` 的延迟导入表里,只有这四个是第三方会占用名字的图形 DLL。

**未走的路(以及为什么)**:把 `d3d11.dll` / `dxgi.dll` 从游戏根目录删掉、或让 ENB
改用别的代理名,都是在要求玩家改自己的 mod 列表;给辅助进程换一个不在游戏根目录的
路径,则要动 CEF 的 `browser_subprocess_path` 与打包布局,收益不抵风险。

> **教训**:「两个 mod 不兼容」这个结论,在**报错里的进程名不是游戏进程**时就要先怀疑。
> 本例里 `KiLoaderTPProcess` 这一处字样已经指出肇事者是我们自己的辅助进程;
> 顺着「谁在这个进程里、它为什么在这里」查,比顺着「KiLoader 和谁冲突」查快得多。

### 版本策略:把 **1.1.1** 指定为稳定版(推荐版本回到 1.1.1)

两个 README 的横幅推荐版本改为 **1.1.1**,并在版本表里用
`**1.1.1** ⭐ **稳定版**` 单独标出;其余版本行**取消加粗**,保持普通样式,
让「哪一个是稳定版」一眼可辨。中英文两版同步。

> **这一条与 §35 的记录并不矛盾,是同一个判据的两种用法。** §35 里门禁抓到的
> 「推荐版本落后两版」,指的是**无人维护造成的漂移**:横幅停在 `1.1.1`、
> 而最新 tag 已经到 `1.1.4`,谁也不知道该装哪个。现在横幅回到 `1.1.1`,
> 是**有理由的选择**,并且这个理由写在横幅里、由门禁绑住(见下):
> `1.1.2 ~ 1.1.4` 照常出货、照常可联机,只是**未被指定为稳定版**。
> 两者的区别不在数字,在于**说不说得清为什么**。

门禁相应扩了 `recommended-version` 这条(没有新开一条检查):横幅指定的推荐版本,
必须**正是**版本表里标了 ⭐ 稳定版的那一行。这样「横幅说 1.1.1」与「表格标 1.1.1」
不会各自漂移,也顺带保证表里**恰好只有一行**是稳定版 —— 两行都标、或一行都没标,
都会红。四条分支(横幅与标记不一致 / 两行都标 / 一行都没标 / 中英各自不一致)
都做了反向验证。

同时把版本表行的识别放宽到允许数字后面跟稳定版标记(`**1.1.1** ⭐ **稳定版**`),
但**只允许这一个标记**:第一版放宽成「数字后面跟任意内容」时,
`| 1.5.3 ~ 1.5.97(老 SE) |` 这类**游戏版本表**的行也会被当成版本表行,
于是缺行可以用无关的行蒙混过去 —— 正是这条检查存在的意义被它自己绕开了。
已收紧为只匹配 `⭐ **稳定版**` / `⭐ **stable**`,并做了反向验证。

### 文档与约束:让"文档更新"成为可检查的规则

`CODE_GUIDELINES.md` 新增一节 **Documentation is part of the change**:
**每次版本修改必须在同一个提交里更新文档**,并且发 tag 之前必须先过一遍
`Tools/Scripts/check_docs.py`。光写规则没用,所以规则配了一条门禁
(已接入 `plugins.yml`,并在 `docs/RELEASE-AND-MO2.md` 的发版步骤里前置)。

新增 `Tools/Scripts/check_docs.py`,四项检查:

| 检查 | 断言 |
| --- | --- |
| `coverage` | 所有引用 1.5.x 覆盖率的文档都必须引用**当前**数字;历史口径必须显式标注"已被取代/当时" |
| `version-tables` | 两个 README 的版本表必须覆盖 CHANGELOG 的每一个版本,且两者**互不矛盾** |
| `tags-have-sections` | 每个已打的 tag 都必须在 CHANGELOG 里有对应小节 |
| `recommended-version` | 推荐版本必须真实存在(有 CHANGELOG 小节),中英一致 |

**它立刻抓到了四处真实问题**,都已修:

- **`v1.1.3` 打了 tag 却没有 CHANGELOG 小节** —— 该版本的内容只存在于两个
  README 的版本表里,CHANGELOG 里既没有 `## v1.1.3` 也没有任何小节。
  已补写完整小节;
- **`v1.1.4` 在两个 README 的版本表里都没有行** —— 版本表停在 1.1.3;
- **覆盖率数字是旧口径**:`README.md`、`README_EN.md`、`Tools/ida/README.md`、
  `docs/LAN-RADMIN-GUIDE.md` 都还写着 3080/3069/11 个,而生成器给的是
  **3082/3069/13 个**;
- **推荐版本落后两个版本**:横幅写着 `1.1.1`,而最新 tag 是 `1.1.4`。

另外把"未映射 id 是**函数**还是**数据**"这条区分写进了两个 README 与
`docs/LAN-RADMIN-GUIDE.md`:函数 id 的桩"调用即返回 0"可以安全调用,
数据 id 不能走同一条路(桩是可执行内存,当数据读会读到机器码)。
这正是 §34 那处修复背后的判据,值得让读者也看得到。

门禁本身写错过两次,**两次都是自测发现的**,都已修正:

- 第一版只检查"文档里出现过正确数字",于是**同一文档里新旧两个值并存时它会通过**
  ——正是它要防的漂移形态。改为枚举文档中**所有**覆盖率形状的数字逐个比对;
- 第二版又太紧:把 `Tools/ida/README.md` 里**有意保留的历史口径**
  (已标注 `Superseded`)误报,还把 `3698/3698 offsets validated` 这个
  **另一个指标**误判成 id 覆盖率。改为"历史口径必须显式标注为历史",
  并排除两边相等的 pair。

还有一处**通过得太容易**的坑:该检查依赖 `git tag`,而 `actions/checkout@v4`
**默认不取 tag**,那样它会跑零次并报告成功。已在 CI 侧显式加
`fetch-depth: 0` 与 `fetch-tags: true`,并在门禁侧加了"一个本仓库的 tag
都看不见就直接报错"的守卫。

顺带记下一个此前没人写下来的事实:**tag 命名空间是共享的**。上游与本仓库
都用 `v1.1.x`,且指向不同提交(本仓库 `v1.1.0` = `03cf2cbb`,
上游 = `fd8748f0`),所以"这个 tag 是不是我们的"必须显式列出系列
(`OWN_TAG_SERIES`)而不是靠名字判断。

### 同步上游 #901:Havok 控制器时间步长(未发布,来自上游 dev)

上游 `dev` 上有 2 个 v1.8.2 之后的提交,其中 `fbf72883`(#901)修的是
**远端 actor 的 Havok 控制器时间步长为 0** 导致的物理污染:

远端 actor 跳过原生移动处理,新建的 controller 因此停在 `deltaTime = 0`。
插值位置更新仍会重置速度,**除以 0 产生非有限加速度**,再传播进接触质量修正 ——
表现就是"物体和 NPC 碰撞后、踩到散落物品后**异常滑行**"。修法是两条:
在远端移动处理里刷新 controller 时序,以及在强制位置更新前刷新、拿不到有效步长时
推迟 controller 定位。涉及 7 个文件(3 个新增)。

**1.5.x 适配(两处,都不是猜的)**:

- 新增的 3 个文件里,`hkStepInfo` 是**纯数据布局**,与版本无关,原样照搬;
  `bhkCharacterController::stepInfo` 的 **0x80 偏移是实测出来的**,不是照抄上游:
  本机有一份真实的 1.5.97 `SkyrimSE.exe`,在其 `.text` 里搜"加载物理步长全局 +
  求倒数 + 通过同一寄存器写 +0x88 与 +0x8C"这一模式,**全镜像只有一处**
  (RVA `0xDBFDD4`,所属函数 `0xDBF630`)。该 RVA 在
  `version-1-5-97-0.bin` 里是真实符号(id `76436`),它读的全局
  (`0x1E083A8`)也是(id `512261`)—— 两头都有名字,不是插值猜出来的。
  0x88/0x8C 即 `deltaTime`/`invDeltaTime`,所以 `stepInfo` 就在 0x80,
  与上游对 1.6.x/1.7.x 的断言一致,**该成员在两代之间没有移动,故不像 `Actor`
  那样需要版本分支**;
- 两个新 id 在 **1.5.97 上都没有映射**(已核对:`39856`、`389089`;
  同一对 id 在 1.6.317/640/1170/1179 与 1.7.99/104 的库里**全部有映射**,
  所以 1.6.x/1.7.x 走的就是上游原路径)。两者性质不同,处理也不同:
  - `39856`(`AIProcess::GetCharController`,`AIProcess.cpp:14`)是**函数 id**。
    `VersionDb.h:60-62` 明文写着桩的契约是"调用它返回 0 而不是崩",
    所以按本仓库既有写法用 `POINTER_SKYRIMSE` + `ThisCall` 是**正确且一致**的,
    未映射时自然得到 `nullptr`,两个调用点都判空跳过刷新;
  - `389089`(物理步长那个 **float 全局**,id 是**数据 id**)**不能**这样写:
    未映射时桩是一段**可执行内存**(`48 31 C0 0F 57 C0 C3`),`*stub()` 是
    **把它自己的机器码当 float 读**。实测那几个字节解码为 `1.895e-29`,
    恰好被 `UpdateDeltaTime` 的 `<= 0.0001` 规则挡掉 —— 但那是**桩的编码
    碰巧**,不是契约:换一段解码成大有限值的桩,就会被当成合法步长直接写进
    controller。故改用 `FindAddressById` 显式解析、失败返回 0,与
    `GarbageCollector::Get()`、`LeveledNpcSystem::CanRecordPick()` 处理各自
    未映射数据 id 的做法一致;

**顺带修掉一处我自己引入的空指针面**:上游的 `ForcePosition` 没有解引用
`GetExtension()`,而本仓库的 `Actor::GetExtension()` (`Actor.cpp:285-298`)
在既非 `ExActor` 也非 `ExPlayerCharacter` 时**返回 nullptr**。直接照搬会在
"本来就是要让它更安全的这条路径"上新增一个解引用。已按同文件
`HookSetPosition`(`:201`)的写法判空。

验证:`hkStepInfo` 的退化阶梯用 g++ 编成可执行并**分进程**跑过两种映射状态
(静态缓存"只问一次",同一进程内换映射不会重算,这点也是实测发现的):
1.6.x/1.7.x 有映射 → `deltaTime=0.0166667 / inv=60`;1.5.x 无映射 →
退回移动步长 `0.02 / inv=50`,连移动步长也没有时保留 controller 里已有的值。
另用 g++ 把改过的逻辑连同一份最小 shim 编译运行过,确认签名与调用约定无误。

## v1.1.4(2026-09-26)

同步上游 **v1.8.2**(3 个提交,分叉点 `e0002073`),并按本仓库的多版本逻辑改写了两处
会在 1.5.x 上失效的写法。

### 上游同步

- **#899 按"原始 NPC + 房主选中的模板"重建等级化 NPC**:此前远端角色的 base 被**直接**
  换成房主选中的模板,丢掉了只存在于原始 NPC 上的数据(守卫的名字、默认装备等)。
  现在走引擎自己的 `CreateTemplateActorBase(原始, 模板)`,与单机解析结果一致;
  旧的临时 base 交给引擎的 `GarbageCollector` 回收(与 `RecalcLeveledActor` 同一套策略,
  但**不动**旧实现留下的静态 pick);
- **#893 排除各派系的监狱储物容器**:入狱时没收的赃物/随身物品容器按派系各存一份,
  同步它们等于让一个玩家的物品进另一个玩家的储物箱。现在遍历 `ModManager::factions`
  收集这些容器指针并从对象同步里排除(只比较指针,不读它们的内容);

### 1.5.x 兼容(本次同步的主要风险)

- **`GarbageCollector::Get()` 不再解引用零返回桩**:单例 id `400329` 在 1.5.97
  映射表里**不存在**,而 `POINTER_SKYRIMSE` 对未映射 id 返回的是"零返回桩"——
  照抄上游会变成**解引用地址 0**。已改为直查地址库,未映射返回 `nullptr`,
  调用点判空后保留旧 base(泄漏一个临时 form,不崩);
- **修掉一个上游引入的每帧 Disable/Enable 死循环**:上游用 `GetLeveledPick() == pPick`
  判断"重建完成",而这个值读的是 `SetLeveledCreature`(id `20231`,1.5.97 **未映射**)
  写进去的 extra data ⇒ 比较**永远为假**,`WaitingFor3D` 会每帧重新禁用再启用该角色。
  新增 `LeveledNpcSystem::CanRecordPick()`(只查一次并缓存),不可写时退回本仓库原有路径
  并把完成判定切回 `baseForm == pPick`;
- `TESObjectREFR::SetBaseForm` 更名为上游的 `SetObjectReference`(仅改名,布局不变);
- `TESFaction` 补 `CrimeData` / `ModManager::factions`:偏移不是猜的——
  form 数组自 `0x10` 起、每项 `0x18`、按 FormType 索引,Faction(11)→`0x118`
  与既有 Quest(77)→`0x748` 互相印证,三个 `static_assert` 同时钉住;

### 插件层专项审计

- **服务端可被任意玩家一条聊天命令打崩**:`CommandService::OnSetTimeCommand` 对
  `m_adminSessions` 里每个连接调 `PlayerManager::GetByConnectionId(session)->GetId()`,
  **不判空**。认证流程里连接 id 在 `GameServer.cpp:896` 先进集合,玩家行到 `:977`
  才建立,而 `:947`(mod 策略不符)、`:983`(重复认证)都会提前返回且**不回头清理集合**
  ——集合只在断线时(`:612`)擦除。该集合的其余所有读者都判了空,其中
  `GameServer.cpp:496-502` 还专门为此打印 `"Admin session not found"`。已改为取到即判、
  失败即 `continue`;
- **修正一处会误导部署的文档**:`docs/COMPANION-PLUGINS.md` 声称"出货的 ini 指向框架运行时,
  所以按名字加载门面的插件仍然走原生传输"——与 `976f9702` 之后的实际出货值**完全相反**
  (ini 里是 `STRBridgeModule=STRPluginMessagingBridge.dll`)。已改写为事实,并写明
  七个随包插件**无一例外**都按名字找门面 DLL、因而**都落在聊天隧道桥接上**;
- `check_transport_compat.py` 增加两条断言,把该文档与**实际出货的 ini 取值**绑死
  (文档必须出现 ini 里的真实值;不得再声称指向框架运行时)。已做反向验证:注入这两种
  回归后门禁均 `exit 1` 并指名道姓;
- **已查明但未改动**(插件仓库是钉死的子模块,本仓库不推送,改了进不了 CI 与发布):
  `STRBridgeModule` 只有**一个**键,而运行时按游戏版本有两个名字
  (`SkyrimTogetherRuntime.dll` / `SkyrimTogetherRuntime_1_5.dll`),门面的加载器又是
  精确模块名匹配 —— 单份 ini 表达不了两者。两条候选修法都**需要实机验证**,
  本轮不翻转行为,已连同证据与边界写入 `docs/PITFALLS.md` §32;
- **新增本仓库自持的插件补丁机制**(见下),并用它修掉了
  `DAVSyncTogether` 的一处崩溃:`DAVConfigIndex::Load()` 里
  `recursive_directory_iterator` 的构造落在循环内 `try` **之外**,而 `Load()` 由
  `OnSKSEMessage(kDataLoaded)` 直接调用、`main.cpp` 又没有 handler ⇒
  `filesystem_error` 逃出 SKSE 消息回调即 `std::terminate`。触发条件很平常:
  `Data/SKSE/Plugins/DynamicArmorVariants` **存在但不是目录**(残留的同名文件)。
  已改用 `error_code` 重载,枚举失败只记一行日志;
- **删掉 `IEDSyncTogether` 的 `RelayHost` 子选项**:它唯一的作用是打开旧 UDP 传输,
  而该传输**根本没被编译**(CMake SOURCES 里没有 `UdpTransport.cpp`/`StrTransport.cpp`/
  `SyncService.cpp`/`Config.cpp`),勾了也不会有任何效果——与其留一个装样子,
  不如删掉。同时把"随包的 `IEDSyncTogether.ini` 目前是惰性的"写进清单
  `payloadNote`,免得有人报"我的配置被忽略"。

### 新增:本仓库自持的插件补丁机制

七个插件是**钉死的子模块**,指向本仓库**没有权限推送**的仓库(已实测:
`git push --dry-run` 对 `Caelvanost/DAVSyncTogether` 返回 `403`;两个上游的 HEAD
又恰好等于当前 pin,所以也没有"等上游修"这条路)。而 CI 的
`git submodule update --init --force --recursive --depth=1` 会**丢弃工作树里的一切改动**
—— 于是"在子模块里改一行"这种修法**永远进不了包**。

新增 `Code/plugins/patches/<plugin>/*.patch` + `Code/plugins/tools/plugin_patches.py`
把这条件拆掉:补丁是本仓库的**普通内容**,照常 review、照常随包发布,在插件被
configure/build **之前**应用到子模块工作树上。

| 命令 | 用途 | 在哪跑 |
| --- | --- | --- |
| `apply` | 应用全部补丁(**幂等**:已应用则跳过) | `windows.yml`,紧跟 checkout、在 build 之前 |
| `verify` | 每个补丁都必须仍能打到 pin 上 | `plugins.yml`,与其它门禁并列 |
| `check` | 当前工作树里补丁是否已应用 | 本地 |
| `revert` | 反向应用,回到 pin | 本地 |

`verify` 用 `git apply --check --cached`(对**索引**而不是工作树),所以"已经应用了"
**掩盖不了**"这个补丁已经配不上新的 pin"——这正是重新 pin 时最需要拦住的失误。

同时改了 `plugin_snapshot.py`:快照门禁原来比对**工作树**,补丁一应用它就误报
"snapshot differs"。现在它通过 `git show <pin>:<path>` 读**pin 的那个提交**的内容,
量的仍然是"备份是否还等于被构建的那个提交",而不是"工作树是否干净"。
两种状态(已打/未打)都实测通过,篡改快照仍然会被抓住。

### 清单

- `Tools/missing_1_5_97_ids.txt`:新增三个未映射 id(`20231`、`36460`、单例 `400329`),
  覆盖率 **3069/3080(99.6%)**。顺带修掉生成器 `collect_codebase_ids()` 的两个口径错误
  (`*.[ch]pp` 通配漏掉全部 301 个 `.h`;注释掉的调用被当成活的),旧口径 3075 因此
  既漏 8 个又虚增 3 个;
- `docs/PITFALLS.md` §3.1:记录本次同步的两处判断与查证手段。

## v1.1.3(2026-09-26)

**插件生态落地**:把剩余三个插件按同一配方并入,可选插件由 3 个增至 6 个。

> 本节是**补写**的。`v1.1.3` 当时打了 tag,却没有在 CHANGELOG 里留下任何小节——
> 该版本的内容只存在于两个 README 的版本表里。`Tools/Scripts/check_docs.py`
> 的 `tags-have-sections` 检查把这类"打了 tag 却无人可读"的发布挡住了,
> 本节即由该检查发现后补齐。

- 并入 `AnimSyncTogether`(动画图谱变量/事件同步)、`DAVSyncTogether`
  (Dynamic Armor Variants 外观同步)、`TradeTogether`(玩家间物品与金币交易),
  子模块、契约校验、打包清单、CI 构建、耐久快照、安装向导六处同步更新;
- 删除 FOMOD 里那段**两条指引都是死路**的 OStim 提示(上游既无 release 也无 tag,
  该脚本又从不进包),中英文改为只描述功能;
- 修复**自己引入的发布阻断**:两个插件 pin 的 vcpkg baseline 在 CI 的
  `--depth 1` 克隆里取不到,而 vcpkg 的 builtin registry 路径**没有 fetch 回退**,
  已改为按 manifest 反推 baseline 再逐个 fetch;
- **OStim 的两个 Papyrus 脚本终于能编了**:改用开源编译器
  `russo-2025/papyrus-compiler`(pin tag + SHA-256),补 12 个基础类型 stub
  (`plugins/` 是 gitlink,只能放本仓库),`OSKSE.pex` / `OStimTogetherNative.pex`
  随包出货,**Add Actor 同意门控真正可用**;
- 顺带修掉 `OStimTogether_OCum.esp` **出货却不带脚本**的缺口(补 4 个 `Form` +
  1 个 `Game` stub,`OStimTogetherOCum.pex` 接入同一编译通道),并让打包脚本支持
  **子选项的 artifacts**(原先静默忽略);
- `GameFiles/Skyrim/scripts/source/` 的 10 个出货脚本补上可复现的编译入口,
  其中 `SkyrimTogetherVerifyLaunchScript.psc` 修掉编译器不支持的 `\n` 转义
  (它会**静默产出字面反斜杠**);归档 papyrus-compiler 源码到 `snapshots/tools/` 并加门禁。

## v1.1.2(2026-09-26)

第四轮审计:全仓复查 + 插件层专项,以及**一次真实缺陷的回滚**。

### 稳定性修复(全部为可复现的空指针)

- **服务端可被远程打崩**:同一连接上发第二次 `AuthenticationRequest` 时
  `PlayerManager::Create` 返回 `nullptr`,而调用点直接解引用。已改为拒绝重复认证;
- **`PlayerService` 三个每帧路径**在载入/主菜单(此时没有玩家)解引用空玩家指针:
  `RunRespawnUpdates`、`RunBeastFormDetection`、`RunDifficultyUpdates`;同文件另两处
  本来就判空,这三处漏了;
- **`DiscoveryService::DetectGridCellChange`**:`GetParentCellEx()` 与坐标回退
  **都**可能为空,而下一行直接读 `pCell->formID`。同文件另外两处对同一个调用都判了空;
- **`CalculateHealthPercentage`**:每帧传入 `PlayerCharacter::Get()`,函数内部不判空;
- **`WeatherService`** 三处 `Sky::Get()->` 未判空(其中一处由服务端消息驱动),
  同文件另外两处判了空;
- **`OverlayService`/`PartyService`/`InputService` 五处 `GetOverlayApp()->`**:
  该指针在 `Create()` 之前为空,而组队事件正是连接后立刻会到的;
- **`baseForm` 空指针**:仓库自己的调试视图里就写着 `if (!pRefr->baseForm)`,
  但 12 处日志/分支直接解引用它(含每帧的裸体检查与网络驱动的物体/魔法/角色路径);
- **`EntitiesView` 一个死守卫**:先写 `"UNNAMED"` 又在下一行无条件 `sprintf_s` 覆盖它,
  等于没判。

### 插件层(专项)

- **ProxyResolver 的映射监听器从来没被调用过**:`OStimTogether` 与 `IEDSyncTogether`
  都注册了 `registerListener`,而框架只把回调存起来、从不触发;OStim 的反向映射
  (`_connectionByProxy`)因此永远是空的,而它的注释写着这条映射是 "Required"。
  现在由 `on_construct/on_destroy<PlayerComponent>` 触发 `kAdded`/`kRemoved`
  (`FormIdComponent` 每实体只写一次、拆除时移除,所以这两类事件就是全部迁移);
- **`setLogCallback` 存了不用**:插件装上的回调永远不会被调用。现在框架自己的
  插件层诊断(丢弃超长 channel / 超限载荷)会通过它发出,且**在锁外**调用;
- **`setLocalDisplayName` 存了不用**:如实注明这是**有意不上线**的——
  发送者显示名只能来自服务端认证过的登录名,否则任何插件都能冒充别人;
- **服务端限流桶泄漏**:`m_buckets` 以单调递增、永不复用的 `PlayerId` 为键且从不清理,
  长开的服务器会一直涨。现在随玩家行一起移除。

### 快捷键:只保留 F2

按需求把**除 F2 以外的所有游戏内快捷键**注释或禁用:

| 键 | 原用途 | 处理 |
|---|---|---|
| **F2** | 联机菜单 | **保留**(唯一) |
| 右 Ctrl | F2 的别名 | **移除**(第二个绑定=第二个要维护的东西) |
| F3 | 调试菜单栏 | `#if 0`;`toggleDebugUI` 绑定仍在,变成纯 opt-in |
| F4 | 揭示其他玩家 | 移除按键;`reveal players` 按钮照常工作 |
| F6 | Discord 覆盖层解锁 | 置于 `if (false && …)`,并在注释里写明重新启用覆盖层时不得复活 |
| F7/F8 | 开发快捷方式 | 保持 `#if 0` |

### 版本支持(1.5.x / 1.6.x / 1.7.x)

- 复核 `VersionDb` 三条加载路径:format 1(1.5.x,SE id 经 ae-to-se 映射表翻译)、
  format 2(1.6.x AE)、format 5(1.7.99+ 密集偏移数组);
- **34 个地址库文件还原**(见上),1.5.x 的 10 个 `.bin` + 10 张映射表、
  1.6.x/1.7.x 的 13 个 `versionlib` 全部在位;
- `GamePatch::At` 的按版本偏移与 `legacyMeasuredOn` 前缀校验保持原样(1.5.97 之外的
  1.5.x 不会被套用 1.5.97 的偏移)。

### 上一轮遗留

- **修复地址库文件误删**:上一个提交在搬移 `STRPluginMessagingAPI.ini` 时,
  连带删掉了 `GameFiles/Skyrim/SKSE/Plugins/` 下**全部 34 个**地址库文件
  (`version-*.bin` 10 个、`versionlib-*.bin` 13 个、`versionlib-ae-to-se-*.map` 11 个)。
  打包路径直接吃 `GameFiles/Skyrim/`,少了它们玩家一启动就会"地址库失败"并退出。
  **34 个文件已按删除前的 blob 哈希逐一还原**;
- **`#if 0` 逐块判读**:22 处 → **删 15 留 7**。留下的 7 处都是"改 0 为 1"型开关
  (F6/F7/F8、旧战斗瞄准 ×3、地图菜单、imgui 上游 ×2),判据是**块外有没有为它留位置**;
- **debug 天气开关从未生效**:`Sky` 三个 hook 里的 `s_shouldUpdateWeather` 判据
  全在 `#if 0` 里,开关写了个没人读的变量。判据已启用(该变量只由 debug 窗口写,
  而该窗口在 release 版被裁掉,所以对发布版无影响);
- **EF 哨兵结论写进代码**:查清 SKSE 插件路径**本来就不需要** `_initterm_e` 哨兵
  (SKSE 已先加载 EF,我们的 hook 装在其 thunk 之上),只补注释、不改逻辑;
- **发布冻结解除**:`RELEASE-FREEZE.md` 删除,README 中英横幅同步移除;
  `release.yml` 的 guard 保留(冻结文件仍是唯一开关)。

- **修复地址库文件误删**:上一个提交在搬移 `STRPluginMessagingAPI.ini` 时,
  连带删掉了 `GameFiles/Skyrim/SKSE/Plugins/` 下**全部 34 个**地址库文件
  (`version-*.bin` 10 个、`versionlib-*.bin` 13 个、`versionlib-ae-to-se-*.map` 11 个)。
  打包路径直接吃 `GameFiles/Skyrim/`,少了它们玩家一启动就会"地址库失败"并退出。
  **34 个文件已按删除前的 blob 哈希逐一还原**;
- **`#if 0` 逐块判读**:22 处 → **删 15 留 7**。留下的 7 处都是"改 0 为 1"型开关
  (F6/F7/F8、旧战斗瞄准 ×3、地图菜单、imgui 上游 ×2),判据是**块外有没有为它留位置**;
- **debug 天气开关从未生效**:`Sky` 三个 hook 里的 `s_shouldUpdateWeather` 判据
  全在 `#if 0` 里,开关写了个没人读的变量。判据已启用(该变量只由 debug 窗口写,
  而该窗口在 release 版被裁掉,所以对发布版无影响);
- **EF 哨兵结论写进代码**:查清 SKSE 插件路径**本来就不需要** `_initterm_e` 哨兵
  (SKSE 已先加载 EF,我们的 hook 装在其 thunk 之上),只补注释、不改逻辑;
- **发布冻结解除**:`RELEASE-FREEZE.md` 删除,README 中英横幅同步移除;
  `release.yml` 的 guard 保留(冻结文件仍是唯一开关)。**本次不打 tag。**

## v1.1.1(2026-09-25)

第三轮审计。本轮换了两条新判据(容器迭代中改动、链式解引用),并复核了
前两轮修改本身。

- **链式解引用**:`VisitInteriorCell` 里的
  `PlayerCharacter::Get()->GetParentCellEx()->formID` 在 **load 全程**会取到空
  cell(`VisitCell()` 只在入口判过玩家存在,进内层就不再判);`VisitExteriorCell`
  的坐标回退也可能为空。两处都已补；
- **`Actor::Create`** 取玩家后**连续解引用三次**,已改为取到即判、失败即返回；
- **`DebugService`** 对 `Actor::Create` 的返回值从未判空就连续解引用,
  且 `PlayerCharacter::Get()` 与 `baseForm` 同样未判——一并补上；
- **修正上一轮自己引入的缺陷**:`Actor::Create` 的玩家判空曾被插在
  `New()` **之后**,提前返回会泄漏刚分配的 actor。已改为**先判空、再分配**；
- 容器迭代类判据(10 处)逐个核对后确认**全部安全**:代码库统一采用
  "先收集、后改动"或"循环外 clear"。

## v1.1.0(2026-09-25)

性能与同步的算法级改进,以及两轮全仓库审计。

- **插值改 Catmull-Rom**:远端玩家移动由线性改为三次曲线,线段交界处方向连续;
  丢包时不再"冻结—跳变",改为沿最后速度做**有界外推**(上限 1.25),并对
  播放头落后窗口的情形补了下限 0,避免反向外推;
- **帧循环 16 ms → 8 ms**:`SetTimer` 按 15.625 ms 系统 tick 向上取整,
  16 ms 实为 31.25 ms(约 32 次/秒),8 ms 落在单个 tick 内(约 64 次/秒),
  远端玩家采样率翻倍;
- **移动更新复杂度**:`OnReferencesMoveRequest` 由 O(更新数 × 实体数)
  降为 O(实体数 + 更新数)(先建 serverId 索引再查表);
- **修复重复生成同一远程玩家**导致引擎在 `SkyrimSE.exe+0x23d000` 解引用空指针
  的崩溃;重复守卫补 `LocalComponent` 检查;
- **全仓库 `GetById` 解引用审计**(两轮,判据不同):修复 15 处无守卫解引用,
  含 `Actor::Create` 对玩家的连续三次解引用、`PlayerService`/`PartyService`
  对硬编码全局的写入(断线路径也写,退出时崩)、`VisitInteriorCell`
  在 loading 期间对空 cell 的链式解引用等;
- 热路径日志降级:启动首秒曾写 220 行,现降至 debug。

## 历史沿革

本项目 fork 自 [TiltedEvolution](https://github.com/tiltedphoques/TiltedEvolution),
其 GitHub fork 链为 `tiltedphoques/TiltedEvolution` → `rfortier/TiltedEvolution-rwf`
→ 本仓库。

本文件此前保存的是**上游 2022 年 7 月之前**由工具自动生成的 changelog
(最后一条为 v1.38.3,2022-07-01),与本仓库使用的版本号体系(`1.0.x`)无关,
留在根目录容易让打包/报错的人对不上号,因此移除;需要那段历史可查上游仓库,
或本仓库的 git 历史(该文件在移除此内容前已被完整提交过)。
