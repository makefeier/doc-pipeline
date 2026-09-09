# doc-pipeline

**规格驱动的文档装配产线**（LangGraph 可选 + 回溯机制）：把"长文档一次性生成总是丢内容/烂尾"变成**分节生产、逐节验收、定点回溯**的流水线。

## 它解决什么问题

让 LLM 一次性生成 5000+ 字的结构化文档（SKILL.md / 报告 / 规范），失败模式高度稳定——丢章节、留占位符、篇幅失衡；整篇重写成本高且换一批新错误。

本产线的核心思想：**把失败局部化**。第 2 轮 8 节通过、2 节缺元素时，回溯只揪出那 2 节、精确到"缺什么"，8 个好节原封不动——修复成本从 O(全文) 降到 O(坏节)。

## 快速上手

```bash
# 1. 任意文档目录，建一份规格
cat > sections.json
{
  "name": "my-doc",
  "h1": "我的文档标题",
  "sections": [
    { "id": "s01", "title": "第一节标题", "minlen": 200, "requires": ["关键词A", "关键词B"] }
  ]
}

# 2. 逐节写草稿到 drafts/s01.md ...

# 3. 跑产线（langgraph 未安装会自动降级内置执行器，行为一致）
python doc_pipeline.py <doc_dir>            # 全绿→组装写盘；有失败→定点修复报告，exit 1
python doc_pipeline.py <doc_dir> --reset    # 清空尝试历史
```

## 回溯机制

- **失败局部化**：校验失败只报坏节 + 精确缺失项，好节不可变
- **尝试预算**：`state.json` 记账每节尝试次数（默认 3 次/节），超限告警"换方法而非重试"——同一招失败三次还不换思路，是 agent 工程里最常见的死法
- **回溯即终结本轮**：退出码 1，等作者修完坏节重跑，不做图内自动重写（自动重写 = 换个姿势赌运气）

## 校验器：故意只做结构判定

最小长度 / 必需关键词 / 禁占位符（`[placeholder` / TODO / 待补）。**故意不做语义判定**——LLM 自检会说"我写全了"，机器判定零幻觉、零成本、可复现。必需关键词同时是防漂移锚：补齐关键词的过程本身让文档更完整。

## 实战用户

| 仓库 | 说明 |
|---|---|
| [value-lens](https://github.com/makefeier/value-lens) | 万物价值评估引擎（含 [DESIGN.md](https://github.com/makefeier/value-lens/blob/main/DESIGN.md)：图结构 / 回溯机制 / 三轮实测记录）|
| [jargon-buster](https://github.com/makefeier/jargon-buster) | 行业黑话击穿引擎 |

同一个"懂行家族"系列还有 [phone-buying-guide](https://github.com/makefeier/phone-buying-guide)（手机选购）与 [insider-compass](https://github.com/makefeier/insider-compass)（不求人 · 交易攻防）。

## License

MIT
