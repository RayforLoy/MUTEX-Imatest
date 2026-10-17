"""Refresh the user-visible catalogue from the same rules used by the product."""
from pathlib import Path
from mutex_imatest.evaluation_catalog import REFERENCES, REFERENCE_VERSION, reference_for
from mutex_imatest.analysis_catalog import METRICS

ROOT=Path(__file__).resolve().parents[1]
INTRO='''# 测量评价、参考值与自定义目标

## 在软件中使用

点击当前画面的彩色评价标签，或打开「评价与参考」页；每个测点在「测量明细」中另列评价。「所选分析结果」并列中位数、最差值、覆盖率及参考。左侧所有项目（含暂不可用项）均有悬停说明。

在「图像质量 → 评价参考与自定义目标」中修改验收方式。目标可用下限、上限或允许区间，包含边界，并保存单位和说明；支持导出 / 导入目标 JSON。频率单位在每个测点按局部尺度换算，切换预览单位不会改变验收。可以关闭工程分档。应用到当前结果及后续分析；只重新解释已有测量，不重算像素。

## 如何读评价

绿色「工程参考良好」仅表示符合公开标注的 MUTEX 建议；绿色「符合自定义目标」仅指用户设置的范围。黄色为留意或结论受限，红色为建议改善或未达自定义目标。蓝色为结果解读，灰色为待设目标或无法评价。无效、低置信度、缺失值不填零；有效覆盖的分母保留这些测点。

无统一优秀线的项目不会虚构等级。MTF / CTF 同图案、方法、方向和通道的本帧最高值比值用于相对比较，不是器材排名。G 的零位移由定义得到，不代表独立的配准验收。

目标受限时保留原因：例如未知输入曲线、剪切、混叠、超奈奎斯特或图卡测试上限。动态范围的实测下界低于目标下限时不能判失败，更不能判通过；高于上限的已知下界则可以判未达上限。焦位不确定度触及限值时结论受限；其拟合不确定度不涵盖载台、图卡与重复性系统误差。

## 导出与可追溯性

HTML 和 PDF 使用同一评价器；旧结果可直接重评，无须重新测量。启用数据附件时，evaluation-results.json / CSV 保存各测点原始数值、单位、评价、限制、参考、标准和规则版本；result.json 的 evaluation_summary 保存本次规则快照。关闭数据附件时仍在报告中嵌入评价。工程提示不是 ISO / EMVA / FADGI 认证。
'''


def main():
    parts=[INTRO,f'规则版本：{REFERENCE_VERSION}。共 {len(REFERENCES)} 个测量项目；另见 [工作台评价](WORKFLOW_EVALUATION.md)。\n','## 全部测量项目\n']
    sources={}
    for name,key in METRICS:
        r=reference_for(key)
        parts += [f'### {name} — {key}\n',f'- 参考值：{r["reference"]}\n- 评价标准：{r["criteria"]}\n- 适用条件：{r["prerequisites"]}\n- 建议：{r["action"]}\n- 依据性质：{r["basis"]}\n']
        for source in r['sources']:
            if source['url']:sources[source['url']]=source['title']
    parts += ['## 定义出处\n','以下资料用于核对定义与限制；文中 MUTEX 工程分档由本项目给出，不是这些机构规定的合格线。\n']
    parts += [f'- [{title}]({url})' for url,title in sources.items()]
    target=ROOT/'docs'/'MEASUREMENT_EVALUATION.md'
    target.write_text('\n'.join(parts)+'\n',encoding='utf-8')
    print(target)


if __name__=='__main__':main()
