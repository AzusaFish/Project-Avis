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

1. 把LLM更换为更新的InternVL-14B（但保留原来的Qwen14B经Unsloth微调后模型接口）模型已存至D:\AzusaFish\Codes\Development\Project-Avis\Model\Base\InternVL14B，新增屏幕截图tool，允许LLM截图查看桌面。（用的是llama.cpp的llama-server）

2. ~~修改静默后主动挑起话题为主动挑起话题/使用工具并且更改逻辑。目前静默时间计数有问题，貌似用文字与LLM对话不会影响计数。此外，让LLM动态维护一个当前对话所需积极度，根据积极度增加/减少主动挑起话题间隔。e.g 当前用户暂时离开->对话积极度降至极低，几乎不主动挑起话题。 (tool除外)~~（阶段1已完成：动态静默窗口+积极度驱动+低积极度抑制主动开话题）

3. ~~如果系统提示静默让挑起话题，LLM可以选择不挑起话题。~~（已完成：静默事件允许 action=idle）

4. ~~KV Cache压缩 （token达到一定量向LLM发送请求对对话进行压缩并替换context_manager像LLM输入的短期记忆。~~（已完成：超阈值触发 LLM 上下文压缩，使用“KV摘要 + 最近轮次尾部”替换短期上下文输入）

5. ~~Live2D 根据kokoro等TTS输出的语音大小控制嘴型。目前更改面部表情的功能貌似无法正常工作。~~（已完成：前端 TTS 音量驱动口型 + 表情调用容错增强）

6. ~~引入异步的记忆总结与反思机制。可以利用闲置的 CPU 资源（AMD 9700X 处理这种后台轻量级任务非常轻松），定期（比如每晚或累积 100 轮对话后）触发一个后台的 LLM 总结任务。让模型分析最近的 SQLite 记录，提取出你的新偏好、新经历，转化为高密度的文本块（如：“他最近在研究嵌入式系统”），然后存入 Chroma 数据库。这样 Avis 就能拥有真正的长期动态记忆。~~（已完成：新增 memory_reflector 后台任务，按“每日窗口/累计轮次”触发总结并写入 Chroma 长期记忆集合）

7. ~~做一个config.html/debug.html，可视化修改config/debug~~（已完成：新增 `live2d-desktop/public/config.html` 与 `live2d-desktop/public/debug.html`）

8. ~~做一个可视化的记忆管理系统。tauri~~（已完成：新增 `live2d-desktop/public/memory.html`，支持查询/编辑/删除/清空记忆）