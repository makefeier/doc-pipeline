# -*- coding: utf-8 -*-
"""
doc_pipeline —— 规格驱动的文档装配产线（通用引擎 v2.1，LangGraph 可选 + 回溯机制）
从 value-lens/pipeline.py（v1）泛化而来：图结构、回溯机制、尝试预算全部不变；
把"章节清单/必需元素/标题/H1"从代码里外置到目标目录的 sections.json，
从此任何长文档都能上这条产线（当前用户：skills/value-lens、skills/jargon-buster）。
运行环境：langgraph 可选——已安装则用 StateGraph 编排，未安装自动降级到内置
线性执行器（同一套节点/条件路由/回溯/预算逻辑，结果一致）。

文档目录契约：
  sections.json   规格：{name, h1, sections:[{id,title,minlen,requires}]}
  drafts/sXX.md   各节草稿（校验与回溯的最小单元）
  SKILL.md        既有文件仅用于提取 frontmatter（可不存在，此时输出不带 fm）

用法:
  python tools/doc_pipeline.py <doc_dir>          # 校验+组装（全绿写盘）或出定点修复报告
  python tools/doc_pipeline.py <doc_dir> --reset  # 清空该文档的尝试历史
"""
import json, re, sys, time
from pathlib import Path
from typing import TypedDict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MAX_ATTEMPTS = 3
BANNED = [r"\[placeholder", r"TODO", r"待补"]


class St(TypedDict):
    round: int
    drafts: dict
    failures: list
    fix_report: dict
    assembled: str
    status: str


def load_spec(doc: Path):
    spec = json.loads((doc / "sections.json").read_text(encoding="utf-8"))
    sections = [(s["id"], s["title"], int(s.get("minlen", 120)), s.get("requires", []))
                for s in spec["sections"]]
    return spec, sections


def make_steps(doc: Path, spec: dict, sections: list):
    """节点工厂：全部节点为闭包纯函数，图编排与线性执行共用同一套实现。"""
    state_f = doc / "state.json"
    drafts_dir = doc / "drafts"

    def load_state():
        if state_f.exists():
            return json.loads(state_f.read_text(encoding="utf-8"))
        return {"attempts": {sid: 0 for sid, *_ in sections}, "history": []}

    def save_state(s):
        state_f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

    def n_plan(st: St) -> St:
        print(f"▶ [{doc.name}] plan: 载入规格（{len(sections)} 节）与历史状态")
        st["failures"] = []
        st["fix_report"] = {}
        st["drafts"] = {}
        return st

    def n_collect(st: St) -> St:
        print(f"▶ [{doc.name}] collect: 收集章节草稿")
        for sid, title, _m, _r in sections:
            f = drafts_dir / f"{sid}.md"
            st["drafts"][sid] = f.read_text(encoding="utf-8") if f.exists() else ""
            if not st["drafts"][sid]:
                st["failures"].append({"sid": sid, "title": title, "missing": ["文件不存在或为空"]})
        return st

    def n_validate(st: St) -> St:
        print(f"▶ [{doc.name}] validate: 逐节校验（必需元素 / 长度 / 禁占位符）")
        already = {f["sid"] for f in st["failures"]}
        for sid, title, minlen, reqs in sections:
            if sid in already:
                continue
            text = st["drafts"][sid]
            problems = []
            if len(text) < minlen:
                problems.append(f"长度不足: {len(text)} < {minlen}")
            for r in reqs:
                if r not in text:
                    problems.append(f"缺少必需元素: {r}")
            for b in BANNED:
                if re.search(b, text, re.I):
                    problems.append(f"含禁止内容: {b}")
            if problems:
                st["failures"].append({"sid": sid, "title": title, "missing": problems})
        if st["failures"]:
            print(f"  ✗ {len(st['failures'])} 节未通过: " + ", ".join(f["sid"] for f in st["failures"]))
        else:
            print(f"  ✓ 全部 {len(sections)} 节通过")
        return st

    def route(st: St) -> str:
        return "assemble" if not st["failures"] else "backtrack"

    def n_assemble(st: St) -> St:
        print(f"▶ [{doc.name}] assemble: 组装（保留原 frontmatter，标题取自规格）")
        src = doc / "SKILL.md"
        fm = ""
        if src.exists():
            parts = src.read_text(encoding="utf-8").split("---\n")
            fm = parts[1] if len(parts) >= 3 else ""
        body = "\n\n".join(
            f"## {i}. {title}\n\n{st['drafts'][sid].strip()}"
            for i, (sid, title, _m, _r) in enumerate(sections, 1)
        )
        fm_block = f"---\n{fm}---\n\n" if fm else ""
        st["assembled"] = f"{fm_block}# {spec['h1']}\n\n{body}\n"
        return st

    def n_gate(st: St) -> St:
        print(f"▶ [{doc.name}] gate: 终检（frontmatter / 无占位符 / 逐节标题存在）")
        t = st["assembled"]
        missing_hdr = [f"## {i}. {title}" for i, (sid, title, _m, _r) in enumerate(sections, 1)
                       if f"\n## {i}. {title}" not in t]
        ok = (t.count("---") >= 2
              and f'name: {spec["name"]}' in t
              and not any(re.search(b, t, re.I) for b in BANNED)
              and not missing_hdr)
        if not ok:
            st["status"], st["failures"] = "gate_failed", [{"sid": "-", "title": "终检", "missing": (["组装结果未过终检"] + missing_hdr)}]
            print("  ✗ 终检未过")
            return n_backtrack(st)
        out = doc / "SKILL.md"
        out.write_text(st["assembled"], encoding="utf-8")
        st["status"] = "done"
        s = load_state()
        s["history"].append({"t": time.strftime("%F %T"), "result": "done"})
        save_state(s)
        print(f"  ✓ 已写入 {out.name}（{len(t)} 字符）——任务完成")
        return st

    def n_backtrack(st: St) -> St:
        s = load_state()
        for f in st["failures"]:
            s["attempts"][f["sid"]] = s["attempts"].get(f["sid"], 0) + 1
        s["history"].append({"t": time.strftime("%F %T"), "result": "backtrack",
                             "failed": [f["sid"] for f in st["failures"]]})
        save_state(s)
        over = [sid for sid, n in s["attempts"].items() if n >= MAX_ATTEMPTS]
        st["fix_report"] = {
            "本轮失败节": st["failures"],
            "尝试次数": s["attempts"],
            "预算告警": [f"{sid} 已达 {MAX_ATTEMPTS} 次上限，需换方法而非重试" for sid in over],
            "作者指令": f"只修列出的节（改 {drafts_dir.name}/<sid>.md），修完重跑 python tools/doc_pipeline.py {doc.name}；未列节勿动。",
        }
        st["status"] = "needs_fixes"
        print("◀ backtrack: 已生成定点修复报告（不整篇重写）")
        for f in st["failures"]:
            print(f"  ↺ {f['sid']} {f['title']}:")
            for m in f["missing"]:
                print(f"     - {m}")
        if over:
            print(f"  ⚠ 预算告警: {over}")
        return st

    return {"plan": n_plan, "collect": n_collect, "validate": n_validate,
            "assemble": n_assemble, "gate": n_gate, "backtrack": n_backtrack}, route


def build_graph(doc: Path, spec: dict, sections: list):
    """LangGraph 编排；langgraph 未安装时返回 None（由 run_plain 接管）。"""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        return None
    steps, route = make_steps(doc, spec, sections)
    g = StateGraph(St)
    for name, fn in steps.items():
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "collect"); g.add_edge("collect", "validate")
    g.add_conditional_edges("validate", route, {"assemble": "assemble", "backtrack": "backtrack"})
    g.add_edge("assemble", "gate"); g.add_edge("backtrack", END); g.add_edge("gate", END)
    return g


def run_plain(doc: Path, spec: dict, sections: list) -> dict:
    """内置线性执行器：按同一条件路由顺序执行节点（无 langgraph 时的降级路径）。"""
    steps, route = make_steps(doc, spec, sections)
    st = {"round": 1, "status": "init", "drafts": {}, "failures": [], "fix_report": {}, "assembled": ""}
    steps["plan"](st)
    steps["collect"](st)
    steps["validate"](st)
    if route(st) == "assemble":
        steps["assemble"](st)
        steps["gate"](st)
    else:
        steps["backtrack"](st)
    return st


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    doc = Path(args[0]).resolve() if args else None
    if doc is None or not (doc / "sections.json").exists():
        print("用法: python tools/doc_pipeline.py <doc_dir> [--reset]（doc_dir 内需有 sections.json）")
        return 2
    spec, sections = load_spec(doc)
    if "--reset" in argv:
        (doc / "state.json").unlink(missing_ok=True)
        print("state 已重置")
    graph = build_graph(doc, spec, sections)
    if graph is None:
        print("ℹ langgraph 未安装 → 内置线性执行器（同一套节点/回溯/预算逻辑）")
        final = run_plain(doc, spec, sections)
    else:
        final = graph.compile().invoke({"round": 1, "status": "init"}, config={"recursion_limit": 25})
    return 0 if final.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
