# **Project Avis: 系统缺陷与架构优化全景清单 (深度扩充终极版)**

本文档汇总了 Project Avis 核心架构中的关键 Bug、隐式缺陷、不合理的补丁代码，以及针对 16GB 显存环境从纯文本（Qwen 14B）向多模态（InternVL 14B）演进的极致工程实践。本版增加了详细的底层原理解析与代码实操指导。

## **一、 核心逻辑与并发阻塞缺陷 (致命逻辑 Bug)**

### **~~1\. STT 切片阻塞主循环导致前端卡死 (Event Loop Starvation)~~（已完成）**

* **场景重现**：前端开启麦克风后，UI 完全失去响应，甚至无法点击“停止”按钮。  
* **深层原理解析**：  
  * 前端每 100ms 产生一个音频切片并通过 WebSocket 发送 USER\_AUDIO\_CHUNK。  
  * asyncio.create\_task() 是非阻塞的，这导致后端在一秒内发起了 10 个并行的 STT 协程任务。  
  * 这 10 个任务同时去争抢底层的 HTTP 连接池（发往 STT API）或 GPU 算力。当底层资源池耗尽时，这些任务会长期挂起（Pending）。  
  * 随着切片源源不断到来，挂起的任务达到数千个，**Python 的事件循环（Event Loop）彻底被这些挂起的 I/O 任务淹没（Starvation）**，导致主循环 await self.bus.consume() 再也得不到执行时间片，前端发来的其他 WebSocket 指令也被堵在 TCP 接收缓冲区，引发浏览器 UI 线程假死。  
* **终极解决方案**：引入单消费者缓冲队列机制（漏斗模型）。  
  * 主循环收到音频切片后，仅执行 self.\_audio\_queue.put\_nowait(payload)（耗时纳秒级），立即返回处理下一个事件。  
  * 设立单一后台 Worker 串行消费这个队列，哪怕识别再慢，也不会影响主循环的即时响应性。

### **~~2\. 短期记忆角色认知混乱 (LLM Identity Confusion)~~（已完成）** （检查一下，如果有这个问题就修。就目前体验来说应该是没有此问题）  

* **场景重现**：系统运行 10 轮以上对话后，AI 开始说：“你好，我是用户”或者重复自己上一次说的话。  
* **深层原理解析**：大语言模型（如 Qwen/Llama）高度依赖 Chat Template（如 \<|im\_start|\>user\\n...\<|im\_end|\>\\n\<|im\_start|\>assistant）来区分自己和他人的立场。原代码 ContextSlice 组装记忆时，未清洗 short\_history 的前缀，将类似于 assistant: 我是Avis 的文本统统打包进了 {"role": "user"}。这在注意力机制（Attention）层面彻底破坏了角色的隔离边界，导致模型注意力涣散，产生人格分裂。  
* **终极解决方案**：在渲染历史记录时，根据冒号前缀精确映射 role。

### **~~3\. 工具结果的记忆污染 (Tool Result Hallucination)~~（已完成）**

* **场景重现**：当你给 AI 加上搜索或查天气的工具后，它偶尔会回复你：“你刚才发给我一段 JSON 代码是什么意思？”  
* **深层原理解析**：当工具执行完毕并抛出 EventType.TOOL\_RESULT 时，loop.py 错误地将其当作 EventType.USER\_TEXT 写入了 SQLite 记忆库。在下一轮对话时，大模型在历史记录中看到“User 说：{"temperature": 25, "weather": "sunny"}”，它会认为这是用户输入的代码，从而脱离角色设定开始分析代码。  
* **终极解决方案**：工具回调必须使用 {"role": "system"} 或 OpenAI 规范的 {"role": "tool"} 进行隔离记录，绝不能算作用户的对话。

## **二、 隐患排查 (静默失败与性能黑洞)**

### **~~4\. 音频采样率不匹配导致的 Whisper 幻觉病~~（阶段性完成：前端真实采样率上报+后端容错）** (先打通STT链路再管这个)

* **深层原理解析**：  
  * Web MediaRecorder 默认以 44.1kHz（每秒 44100 个采样点）进行录音。  
  * 常见的 Whisper 模型（尤其是在未做动态重采样配置的 CTranslate2 或 transformers 后端中）强依赖 16kHz 的声学特征输入。  
  * 如果你直接把 44.1kHz 的 1 秒音频喂给 16kHz 的 Whisper，模型会认为这是一段时长接近 3 秒的“慢动作”低沉音频。特征矩阵（Mel Spectrogram）的严重形变，会迫使 Whisper 在无意义的杂音中强行解码，输出诸如“感谢观看”、“字幕提供”等内置的训练集高频词（典型的幻觉）。  
* **改写建议**：  
  * **前端控制**：在获取录音权限时显式指定：navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000 } })。  
  * **后端兜底**：使用 scipy.signal.resample 拦截重采样。

### **~~5\. 后台 Worker 缺少看门狗机制 (Worker Silent Death)~~（已完成）**

* **深层原理解析**：asyncio.create\_task 创建的独立协程是一个“孤儿”。如果 STT 调用时突然断网抛出 ConnectionError，而 \_audio\_worker 内没有在最外层写 except Exception 捕获，这个协程会静默挂掉（连报错都不一定输出）。此时主循环虽然还在收音频放进队列，但永远没有消费者去取，STT 彻底变成一个黑洞。  
* **改写建议**：  
  async def \_audio\_worker(self):  
      while self.\_running:  
          try:  
              \# 取出并处理音频  
          except Exception as e:  
              logger.error(f"STT Error: {e}") \# 记录后继续下一次循环，保证不死

## **三、 补丁清理与架构精简 (Codebase Debloat)**

项目中存在大量为了解决早期问题而引入的“妥协性代码”，这些代码在接入现代 14B 大模型后，会成为严重的累赘。

### **1\. “微服务”滥用综合征 (HTTP Bridge Hell) —— 必须铲除**

* **当前状态**：已完成风险评估并**暂停代码改造**，详见 `Core/instructions/HIGH_RISK_REFACTOR_ASSESSMENT.md`。

* **诊断**：Core/bridges/ 目录通过 Flask/FastAPI 将 STT、TTS、Wechat 等组件强行封装成了 127.0.0.1 的本地微服务。  
* **危害**：  
  * **通信税 (Communication Tax)**：每次 TTS 合成或 STT 识别，都要经历 Python 对象 \-\> JSON 序列化 \-\> TCP/IP 网络栈传输 \-\> JSON 反序列化 \-\> Python 对象的完整过程。对于高频对话，这徒增了几十毫秒的延迟。  
  * **系统熵增**：部署时需要额外启动、监控多个独立的进程终端，极易出现某个端口被占用导致部分功能瘫痪的问题。  
* **重构指导**：移除网络层，改为 **多进程模型 (Multiprocessing)**。使用 Python 的 concurrent.futures.ProcessPoolExecutor 维护一个后台进程执行模型推理，通过进程安全队列 (multiprocessing.Queue) 或直接的异步转同步调用进行通信，消灭一切本地 HTTP 端口。

### **~~2\. 移除 Ollama 专属 API 与 Fallback 降级逻辑~~（已完成）**

* **诊断**：llm\_router.py 中写了针对 /api/chat 的定制请求，并在其报错时使用字符串拼接降级调用 /api/generate。  
* **危害**：代码臃肿度增加一倍；/api/generate 没有角色隔离概念，一旦降级，模型幻觉率飙升。  
* **重构指导**：完全删掉 Ollama 专属分支。目前市面上的推理框架（Ollama, vLLM, llama.cpp）均提供标准的 OpenAI /v1/chat/completions 接口。整个 router 只需要保留一份针对 OpenAI 格式的 HTTP 客户端代码。

### **~~3\. 记忆污染补丁：不要篡改用户的原始输入~~（已完成）**

* **诊断**：time\_utils.py 中的 prepend\_user\_time 会把用户的每句话改写为 类似\[2024-03-31 16:55:00\] 你好 然后存入 SQLite。  
* **危害**：浪费大量 Token，且时间戳的不断重复会让模型的注意力机制偏离对话文本本身。  
* **重构指导**：维持数据库中用户输入的纯净性 ("你好")。系统时间感知应该作为一种“运行时环境变量”，在 ContextManager 每次拼接 messages 时，动态注入到 system\_prompt 的最后一行：f"...\[System Context: Current Time is {datetime.now()}\]"。同时也防止前端的输出多添加时间戳问题。

### **~~4\.检查迁移至其他机器的环境以及路径问题~~（已完成）**

* 可能存在部分路径使用的是绝对路径。需要查找并修改。最后完善整个路径的说明.md，防止后期修改文件结构造成无效路径。

### **~~5\. Planner 的正则清洗替换为 Structured Outputs~~（已完成）**

* **诊断**：使用正则表达式从 LLM 输出中强行剥离 Markdown json 。  
* **重构指导**：现代大模型 API 支持传入 "response\_format": { "type": "json\_object" }。一旦开启，推理框架在底层采样 Token 时会自动过滤掉所有非 JSON 字符，从物理层面保证输出必定是合法的 JSON 对象，彻底抛弃应用层的正则补丁。

## **四、 进阶部署：16GB 显存与 InternVL 3.5 14B 多模态**

针对 **RTX 5070 Ti 16GB** 显卡运行视觉语言大模型（VLM）的前瞻性技术约束。

### **1\. 显存精确切分账本 (Memory Budgeting)**

16GB 显存是极其宝贵的，必须精打细算：

* **OS 及杂项**：约 1.5GB  
* **文本基座 (14B Q4\_K\_M)**：约 8.5GB  
* **视觉编码器 (ViT FP16)**：约 2.0GB  
* **KV Cache 余额**：**约 4.0 GB**  
* **部署策略**：强烈推荐使用 llama.cpp，利用其分离式模型架构，分别加载 llm.gguf 和 mmproj.gguf。

### **2\. 铲除隐形显存刺客：ChromaDB**

* **危机预警**：即使你不发图片，只要你 import 了 ChromaDB 并实例化了默认的 embedding 函数，它会在后台自动下载 sentence-transformers 的 PyTorch 模型。如果你的环境有 CUDA，它会自动加载到 GPU 上，**直接吞噬 1GB\~1.5GB 的显存**！这会导致你留给 KV Cache 的 4GB 瞬间缩水三分之一。  
* **强制阻断方案**：在初始化 Embedding 实例时，必须显式锁死在 CPU 上运行。文本向量提取的算力需求极小，CPU 耗时几毫秒即可完成。  
  from chromadb.utils import embedding\_functions  
  emb\_fn \= embedding\_functions.SentenceTransformerEmbeddingFunction(  
      model\_name="all-MiniLM-L6-v2",   
      device="cpu"  \# 核心：誓死保卫 GPU 显存  
  )

### **3\. 视觉 Token 炸弹防御机制 (4K 原图熔断)**

* **技术背景**：InternVL 3.5 使用动态 Patch 机制处理图像。一张 4K 原图 (3840x2160) 会被模型切分为数十个 ![][image1] 的图像块，并转化为超过 **10000 个视觉 Token**！如果你把这种图直接转 Base64 塞给 LLM Router，16GB 显存会当场爆显存 (OOM) 崩溃。  
* **必须实施的图像管道流 (Image Pipeline)**：未来开发图像识别功能时，必须在向 LLM 发送请求前增加以下拦截器：  
  1. **强制降维缩小 (Downscaling)**：使用 PIL 拦截，等比例缩小图片，强制限制最大边长不超过 1024 像素（甚至 512 像素对日常物体识别也足够）。  
  2. **有损压缩 (JPEG Encode)**：将图片转换为 JPEG（质量 80%\~85%），彻底抛弃 RGBA 通道的无损 PNG，这能让 Base64 载荷的体积缩减几个数量级，大幅降低网络 HTTP I/O 延迟。  
  3. **单轮抛弃策略 (Stateless Vision)**：**永远不要将历史回合的图片带入当前 prompt**。数据库历史记录中应只保留模型对该图片的文本描述。Prompt 中包含的 {"type": "image\_url"} 仅限用户刚发送的那一张图片。

### **4\.新功能**

1. ~~把LLM更换为更新的InternVL-14B（但保留原来的Qwen14B经Unsloth微调后模型接口）模型已存至D:\AzusaFish\Codes\Development\Project-Avis\Model\Base\InternVL14B，新增屏幕截图tool，允许LLM截图查看桌面。（用的是llama.cpp的llama-server）~~
~~写一个通过LLaMa_Factory对模型进行微调的代码。现在已经有annotator.py(under \Tuning)~~

2. ~~修改静默后主动挑起话题为主动挑起话题/使用工具并且更改逻辑。目前静默时间计数有问题，貌似用文字与LLM对话不会影响计数。此外，让LLM动态维护一个当前对话所需积极度，根据积极度增加/减少主动挑起话题间隔。e.g 当前用户暂时离开->对话积极度降至极低，几乎不主动挑起话题。 (tool除外)~~（阶段1已完成：动态静默窗口+积极度驱动+低积极度抑制主动开话题）

3. ~~如果系统提示静默让挑起话题，LLM可以选择不挑起话题。~~（已完成：静默事件允许 action=idle）

4. ~~KV Cache压缩 （token达到一定量向LLM发送请求对对话进行压缩并替换context_manager像LLM输入的短期记忆。~~（已完成：超阈值触发 LLM 上下文压缩，使用“KV摘要 + 最近轮次尾部”替换短期上下文输入）

5. ~~Live2D 根据kokoro等TTS输出的语音大小控制嘴型。目前更改面部表情的功能貌似无法正常工作。~~（已完成：前端 TTS 音量驱动口型 + 表情调用容错增强）

6. ~~引入异步的记忆总结与反思机制。可以利用闲置的 CPU 资源（AMD 9700X 处理这种后台轻量级任务非常轻松），定期（比如每晚或累积 100 轮对话后）触发一个后台的 LLM 总结任务。让模型分析最近的 SQLite 记录，提取出你的新偏好、新经历，转化为高密度的文本块（如：“他最近在研究嵌入式系统”），然后存入 Chroma 数据库。这样 Avis 就能拥有真正的长期动态记忆。~~（已完成：新增 memory_reflector 后台任务，按“每日窗口/累计轮次”触发总结并写入 Chroma 长期记忆集合）

7. ~~做一个config.html/debug.html，可视化修改config/debug~~（已完成：新增 `live2d-desktop/public/config.html` 与 `live2d-desktop/public/debug.html`）

8. ~~做一个可视化的记忆管理系统。tauri~~（已完成：新增 `live2d-desktop/public/memory.html`，支持查询/编辑/删除/清空记忆）

---

## **五、记忆模块二期（仅列未完成/部分完成项，按难度排序）**

说明：以下清单基于当前代码状态整理，已落地能力（SQLite 基础对话存储、Chroma 基础检索、memory_reflector 基础总结）不重复列出。

### **L1（简单）—— 先把“短期记忆可控”做扎实（已完成）**

1. ~~短期记忆结构从 dialogue 扩展为可控 Buffer（兼容迁移）~~（已完成：新增 `short_term_buffer`、索引与启动无损迁移，保留旧 `dialogue` 兼容）
   * **目标**：支持上下文窗口裁剪、重要条目钉住、截图路径和情绪标签，避免短期记忆“只有文本”导致后续策略无法落地。
   * **技术细节**：
     * 新建 `short_term_buffer`（或在现有 `dialogue` 基础上增列）
     * 字段建议：`msg_id`、`timestamp`、`role`、`content`、`emotion_vector`(JSON)、`importance_score`(REAL)、`screenshot_path`、`token_estimate`、`processed_flag`
     * 建立索引：`idx_stb_timestamp`、`idx_stb_importance`、`idx_stb_processed`
     * 做无损迁移脚本：`dialogue -> short_term_buffer`，并保留回滚 SQL
   * **验收标准**：
     * 启动迁移后历史对话不丢失
     * 新写入链路可同时写入 `content + importance_score + emotion_vector`
     * API 层可分页查询并按重要度排序

2. ~~上下文窗口管理器（FIFO + 重要记忆钉住）~~（已完成：实现 `recent_window + pinned_items` 双通道并按 token 预算裁剪）
   * **目标**：避免把所有历史硬塞进 Prompt；保证“普通记忆可衰减，关键记忆可保留”。
   * **技术细节**：
     * 取最近 N 条时按双通道拼接：`recent_window + pinned_items`
     * `pinned_items` 规则：`importance_score >= threshold`
     * 先按 token 预算裁剪，再拼接 system 约束
   * **验收标准**：
     * Prompt 长度稳定在预算内
     * 高重要度条目即使超出时间窗仍可被挂载

3. ~~短期记忆写入策略统一（文本/截图/工具结果）~~（已完成：新增 `append_short_term_memory` 统一入口并接入主循环）
   * **目标**：把“IDE 报错截图路径、工具事实、情绪标签”统一写入短期记忆，不再散落在多个事件分支。
   * **技术细节**：
     * 统一入口：`append_short_term_memory(event)`
     * `tool_result` 统一转 `role=system/tool`，避免污染 `role=user`
     * 截图类事件只存摘要，不存大体积二进制
   * **验收标准**：
     * 任意一轮对话都能追溯“文本+工具结果”的完整上下文

### **L2（中等）—— 让“情绪偏见记忆”成为可计算模型（已完成）**

4. ~~情绪化记忆衰减模型（Emotional Decay）~~（已完成：引入 `W_t = W_0 * exp(-lambda * t)`；短期记忆累计到阈值后由 LLM 评审 `importance_score` 与 `emotion_vector`，高强度负面最慢衰减，正面次慢）
   * **目标**：将“普通记忆快衰减，强负面记忆慢衰减”变成可调数学模型。
   * **技术细节**：
     * 核心公式：`W_t = W_0 * exp(-lambda * t)`
     * `W_0` 来源：文本信息量 + 事件严重度 + 情绪强度
     * `lambda` 来源：`emotion_vector` 映射函数（高强度负面 -> 更小 lambda）
     * 每次检索前动态计算 `effective_score = W_t + rule_bonus`
   * **验收标准**：
     * 低价值闲聊在 24-72h 内明显下沉
     * 高价值的经历和情感在同等时间下排名更靠前

5. ~~Chroma 检索升级为“语义 + 时间 + 重要度”混合排序~~（已完成：实现 `semantic_score + recency_score + effective_importance` 混排，并补齐 `topic_tags/emotion_tag/source_event` 元数据）
   * **目标**：避免纯向量相似度导致旧垃圾片段反复命中。
   * **技术细节**：
     * 召回阶段：`top_k_semantic`
     * 重排阶段：融合 `semantic_score + recency_score + effective_importance`
     * Metadata 增加：`topic_tags`、`emotion_tag`、`source_event`
   * **验收标准**：
     * 同主题检索结果中，近期关键记忆优先于陈旧闲聊

### **L3（困难）—— 引入 GraphDB“翻旧账引擎”**

6. **GraphDB 基础接入（Memgraph/Neo4j 二选一）**
   * **目标**：落地实体-关系-事件图谱，支持“你上次也犯过这个错”的因果回忆。
   * **技术细节**：
     * 节点：`Person`、`Event`、`Error`、`Project`、`Emotion`
     * 边：`COMMITTED_AT`、`OCCURRED_IN`、`FEELS`、`RELATES_TO`
     * 统一图谱写入接口：`graph_store.upsert_triplets(triplets)`
     * 幂等键设计：`(subject, relation, object, day_bucket)`
   * **验收标准**：
     * 可执行 Cypher 查询返回最近同类错误事件
     * 重复写入不会造成图爆炸（幂等有效）

7. **Triplets 提取与冲突合并策略**
   * **目标**：把梦境总结结果稳定转换为图谱事实，而不是一次性噪声。
   * **技术细节**：
     * LLM 输出固定 JSON：`[{s, p, o, confidence, evidence_id}]`
     * 低置信度先入“候选区”，高置信度入正式图
     * 冲突关系（同主体同谓词不同客体）按时间与置信度决策覆盖或并存
   * **验收标准**：
     * 图谱新增事实可追溯来源消息 ID
     * 冲突样本不再无脑覆盖

### **L4（很困难）—— 完整离线梦境流水线与 GC 闭环**

8. **将现有 memory_reflector 扩展为完整“梦境固化 Pipeline”**
   * **目标**：把“已有总结写 Chroma”升级为“摘要 + 图谱 + 向量 + 清理”一条龙。
   * **技术细节**：
     * Stage A：从 `short_term_buffer` 抽取未处理记录（24h 窗口）
     * Stage B：LLM 生成 `summary + triplets + tags`
     * Stage C：写入 Chroma（summary）
     * Stage D：写入 GraphDB（triplets）
     * Stage E：GC（删除低价值已固化记录，仅保留高重要锚点）
     * 全流程要求幂等：失败可重跑，不重复写入
   * **验收标准**：
     * 连续运行 7 天后，SQLite 体量稳定不膨胀
     * Chroma 与 GraphDB 都能查到同一事件的“语义+关系”两种视图

9. **可观测性与回归测试（必须项）**
   * **目标**：防止记忆系统变成“看似运行、实际失效”。
   * **技术细节**：
     * 指标：反思触发次数、成功率、单次处理条数、GC 删除量、图谱写入量
     * 增加 e2e 回归样例：
       * 同类错误复发 -> 可召回上次错误
       * 高情绪冲突 -> 衰减后仍可被命中
       * 普通闲聊 -> 若干天后自动下沉
   * **验收标准**：
     * 有可读 dashboard 或 health detail 字段
     * 核心记忆路径具备自动化回归测试

---

## **建议执行顺序（避免返工）**

1. 先做 L1（结构和窗口控制）。
2. 再做 L2（衰减与混合检索）。
3. 然后 L3（GraphDB 与 triplets）。
4. 最后 L4（梦境流水线闭环 + 回归与监控）。

---

## **六、记忆功能快速验收清单（10-30 分钟可判断是否有效）**

### **A. 现有记忆功能（已实现）短验收**

1. **SQLite 短期记忆写入/读取**
  * **快速验收方法（10 分钟）**：连续发送 3 条用户文本 + 3 条助手回复，随后调用记忆查询接口（或 memory 页面）。
  * **通过标准**：6 条都能按时间顺序查到，`role` 不错位，重启 Core 后仍存在。

2. **记忆 CRUD（查询/编辑/删除/清空）**
  * **快速验收方法（10 分钟）**：在 memory 页面执行“改一条、删一条、按 role 清空一类”。
  * **通过标准**：刷新后结果与操作一致；`count` 统计同步变化；无 500 报错。

3. **Chroma 人格语料检索（persona）**
  * **快速验收方法（15 分钟）**：用一个明确主题（如“C++ 指针越界”）提问两次，观察 few-shot 是否包含相关历史语料。
  * **通过标准**：同主题召回稳定，离题召回明显减少。

4. **长期记忆写入与检索（memory collection）**
  * **快速验收方法（15 分钟）**：手动写入 2 条长期笔记（带 metadata），再用关键词检索。
  * **通过标准**：可被检索命中，返回文本与 metadata 对应。

5. **memory_reflector 按轮次触发**
  * **快速验收方法（20-30 分钟）**：临时把 `MEMORY_REFLECT_TURN_INTERVAL` 调小（如 10），进行超过阈值轮次对话。
  * **通过标准**：日志出现 reflector 执行与插入记录；`runtime_meta.reflect_last_dialogue_id` 前进。

6. **memory_reflector 每日窗口触发**
  * **快速验收方法（20 分钟）**：将 `MEMORY_REFLECT_DAILY_HOUR` 设为当前小时并保证有新增对话。
  * **通过标准**：当日仅触发一次；`reflect_last_day` 更新为今天。

7. **KV 摘要持久化恢复（运行时元信息）**
  * **快速验收方法（15 分钟）**：触发一次上下文压缩后重启 Core。
  * **通过标准**：重启后能从 `runtime_meta` 恢复摘要，不会丢失压缩上下文。

8. **记忆可视化页面（memory.html）**
  * **快速验收方法（10 分钟）**：页面执行查询、编辑、删除、清空各一次。
  * **通过标准**：UI 显示与后端数据一致；失败场景有明确提示。

### **B. 二期功能（规划项）快速验收方法**

1. **短期记忆结构扩展（short_term_buffer）**
  * **快速验收方法（20 分钟）**：插入 5 条不同 `importance_score/emotion_vector/screenshot_path` 的样本。
  * **通过标准**：字段完整写入；按重要度排序与按时间排序都正确。

2. **上下文窗口管理器（FIFO + 钉住）**
  * **快速验收方法（20 分钟）**：造 30 条历史，并把 2 条设高重要度。
  * **通过标准**：最终 Prompt 中“最近窗口 + 2 条钉住”同时存在，总 token 不超预算。

3. **短期记忆统一写入策略（文本/截图/工具）**
  * **快速验收方法（20 分钟）**：依次触发普通文本、截图工具、工具返回事件。
  * **通过标准**：三类事件都能通过同一入口入库，且 `role` 分类正确。

4. **情绪化衰减模型（Emotional Decay）**
  * **快速验收方法（30 分钟）**：构造“普通闲聊”与“高情绪冲突”两组样本，模拟时间推进计算 `W_t`。
  * **通过标准**：同样时间下高情绪样本 `effective_score` 显著高于普通样本。

5. **Chroma 混合排序（语义+时间+重要度）**
  * **快速验收方法（30 分钟）**：准备语义相近但新旧不同、重要度不同的样本集进行查询。
  * **通过标准**：重排后“近期+高重要度”样本稳定进入前列。

6. **GraphDB 基础接入**
  * **快速验收方法（30 分钟）**：写入 5 条 triplets，执行 2 条 Cypher 查询（最近错误、项目关联）。
  * **通过标准**：查询结果正确；重复写入不产生重复边。

7. **Triplets 提取与冲突合并**
  * **快速验收方法（30 分钟）**：给同主体同谓词不同客体的冲突样本各 2 条。
  * **通过标准**：系统按置信度/时间规则决策，且保留 evidence 可追溯。

8. **梦境流水线（总结->向量->图谱->GC）**
  * **快速验收方法（30 分钟）**：跑一次端到端 dry-run，记录每个 stage 的输入输出计数。
  * **通过标准**：四阶段都有产出且幂等；GC 后短期库条数下降但关键锚点保留。

9. **可观测性与回归测试**
  * **快速验收方法（30 分钟）**：执行最小回归集（复发错误召回、情绪记忆保留、闲聊下沉）并查看 metrics。
  * **通过标准**：三条回归全通过；health/metrics 能看到触发次数、成功率、删除量、写图量。

