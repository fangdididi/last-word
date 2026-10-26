# Last Word：谁说了算

[English](README.md) | 中文

**文件说法打架时，找出在你关心的那一天真正有效的那一句。**

Last Word 是一个智能体技能，用来从一堆互相修改的文件中回答问题：合同和它的补充协议、制度的多个版本、需求文档加会议决定，以及围绕它们的邮件和群消息。智能体不再照搬搜索到的第一条结果，而是建一张小小的说法台账，按你确认过的“效力阶梯”给文件类型排等级，再按指定日期逐个裁决。答案附带决定性原句、它推翻了什么、有人说过但不具约束力的话，以及即将发生的变化。两个同等级来源说法不同时，它会直说并请你决定，而不是去猜。

适用于 Claude Code、Codex、Cursor，以及任何能读取 `SKILL.md` 的智能体。确定性的部分由一个只用 Python 标准库的辅助脚本完成。

## 为什么需要它

搜索能找到每个版本的“真相”，问题出在之后：

- 引用最新的消息，哪怕一条群聊根本无权修改正式协议；
- 引用看起来最正式的文件，却没注意后来的补充协议已经替换了那一条；
- 把两个来源揉在一起，给出一个没有任何文件写过的“确定”答案。

Last Word 让裁决规则可见、可重复，你十秒钟就能核对它的推理。

## 功能

- **效力阶梯**：由你决定每类文件的分量（法律法规、协议、补充协议、制度、细则、邮件、群聊）。阶梯写在台账里，裁决可以复现。
- **按日期回答**：每个问题都按某个日期裁决，支持 `effective_from`、`effective_to` 和待生效变更。
- **明确替换**：写明“替换”某条的说法会让被替换的那条出局；低等级文件声称替换高等级文件时，检查器会提醒。
- **偏差识别**：比胜出者更晚、等级更低、说法不同的内容会标成“有人说过但不具约束力”，因为大家常照着它办事。
- **如实报告冲突**：同等级、同一天、值不同就给出 CONFLICT 和两个来源，绝不掷硬币。
- **适用范围**：因地区、产品、职级而不同的答案分开处理；需要范围却没说的提问返回 NEEDS_SCOPE。
- **不凭记忆作答**：台账里没有来源涉及的问题，结论就是 NO_SOURCE。
- **时间线与全量扫描**：查看每个时间段适用什么，或一次性检查文件夹里的所有议题。
- **辅助脚本** `scripts/lastword.py`：提供 `lint`、`resolve`、`card`、`timeline`、`sweep`，附 58 个测试。

## 裁决结果

| 结果 | 含义 |
|---|---|
| SETTLED | 该日期有唯一有效值（标记：DRIFT 偏差、CHANGE_COMING 即将变更、DATE_GUESSED 生效日为推定） |
| CONFLICT | 同等级来源在同一生效日说法不同，由负责人决定 |
| NEEDS_SCOPE | 答案因范围而不同，但提问没有指明范围 |
| NO_SOURCE | 台账里没有任何来源涉及这个问题 |
| NOT_YET | 只有晚于该日期才生效的说法 |
| NOTHING_IN_FORCE | 相关说法全部已失效或被替换 |

## 安装

把整个文件夹复制到智能体的技能目录：

```bash
git clone https://github.com/fangdididi/last-word
# Claude Code
cp -R last-word ~/.claude/skills/last-word
# Codex
cp -R last-word ~/.codex/skills/last-word
# Cursor（项目级技能）
mkdir -p .cursor/skills && cp -R last-word .cursor/skills/last-word
```

其他智能体：让它读取 `SKILL.zh-CN.md`（或 `SKILL.md`），并把 `scripts/` 文件夹放在旁边。只需要 Python 3.9 及以上，没有其他依赖。

## 使用方法

可以这样对智能体说：

> “这是报销制度文件夹，2025 年 10 月去上海出差住宿每晚能报多少？用 last word 判断。”

> “按 10 月 1 日扫一遍这个制度文件夹，告诉我哪些已定、哪些冲突、哪些马上要变。”

智能体会先把问题钉住，提出一份效力阶梯请你确认，把所有相关说法收进 `ledger.json`，检查后再裁决。

你也可以自己运行脚本：

```bash
python3 scripts/lastword.py lint examples/travel-policy-zh/ledger.json
python3 scripts/lastword.py card examples/travel-policy-zh/ledger.json \
  -s 住宿 -p 每晚上限 --scope 一线城市 --as-of 2025-10-01 --question "十月去上海住宿能报多少？"
python3 scripts/lastword.py sweep examples/travel-policy-zh/ledger.json --as-of 2025-10-01
python3 scripts/lastword.py timeline examples/freelance-contract/ledger.json -s invoice -p payment_days
```

## 示例

```text
## 2025年10月去上海出差，住宿每晚能报多少？

- As of: 2025-10-01  (scope: 一线城市)
- Verdict: **SETTLED**
- Answer: **600元**
- Last word: 行政通知〔2025〕12号 (制度修订通知, rank 5, in force from 2025-07-01)
  > "自2025年7月1日起，一线城市住宿上限调整为每晚600元。"
- Said but not binding: P4 says **800元** (销售部微信群 2025-09-03 部门助理, rank 1)
- Set aside: P1 SUPERSEDED by P3
```

智能体的回复：“每晚 600 元，依据是 7 月 1 日起生效的行政通知〔2025〕12 号。群里说的 800 元没有制度依据，按 800 报销会被退回。”

更多内容见 [`examples/travel-policy-zh/answers.md`](examples/travel-policy-zh/answers.md) 和 [`examples/freelance-contract/answers.md`](examples/freelance-contract/answers.md)。

## 文件结构

```text
last-word/
├── SKILL.md                      # 技能说明（英文）
├── SKILL.zh-CN.md                # 技能说明（中文）
├── README.md
├── README.zh-CN.md
├── LICENSE
├── scripts/
│   └── lastword.py               # lint / resolve / card / timeline / sweep
├── templates/
│   └── ledger.template.json      # 空白台账，附建议的效力阶梯
├── examples/
│   ├── freelance-contract/       # 合同、补充协议、邮件偏差、SOW 冲突（英文）
│   └── travel-policy-zh/         # 差旅制度：版本、通知、群消息、适用范围
└── tests/
    └── test_lastword.py          # 58 个测试
```

运行测试：`python3 -m unittest discover -s tests`。

## 局限

Last Word 是阅读辅助，不是法律意见。脚本只在去掉首尾空格、转小写后比较文本，所以含义仍需智能体自己判断（比如“三十天”和“30”）。裁决的质量取决于阶梯和台账本身：涉及实际法律或财务后果的事，请和负责人确认这两样。

## 许可证

MIT，见 [LICENSE](LICENSE)。
