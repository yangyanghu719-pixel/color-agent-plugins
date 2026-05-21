from __future__ import annotations
from app.services.qwen_client import analyze_composition_with_qwen


class CompositionAnalyzeService:
    @staticmethod
    def _fallback(payload: dict, model_error: str | None = None) -> dict:
        ops = payload.get('operations', [])
        text=[]
        mp={"move":"元素位置变化可能导致视觉重心偏移","scale":"缩放会改变主次关系和面积权重","rotate":"旋转会改变稳定性或方向感","flip_x":"水平镜像会改变阅读方向和动势","flip_y":"垂直镜像可能改变上下重力感","z_order_up":"上移一层会增强视觉优先级","bring_to_front":"置于顶层会增强遮挡和优先级","z_order_down":"下移一层会弱化主体性","send_to_back":"置于底层会增强背景属性","hide":"隐藏元素会改变画面密度和留白"}
        for op in ops:
            if op.get('type') in mp: text.append(mp[op['type']])
        if not text: text=["本次构图调整改变了元素关系与空间层次。"]
        return {"status":"success","message":"模型暂不可用，已返回基础分析","summary":"；".join(text[:2]),"composition_change":"；".join(text),"visual_focus_analysis":text[0],"balance_analysis":"建议关注视觉重心与留白平衡。","proportion_analysis":"元素面积变化会影响主次层级。","direction_analysis":"方向与动势可通过旋转/镜像强化。","blank_space_analysis":"隐藏或移动元素会改变留白节奏。","layer_order_analysis":"图层顺序会影响遮挡与前后关系。","spatial_relationship_analysis":"前中后景关系由位置和层级共同决定。","learning_explanation":"请对照操作记录观察形式构成变化。","suggestions":["先明确主体，再调整层级与比例","每次只改变一类操作便于比较"],"fallback_used":True,"model_error":model_error}

    @staticmethod
    def analyze(payload: dict) -> dict:
        try:
            md = analyze_composition_with_qwen(**payload)
            return {"status":"success","message":"success","summary":"已完成构图分析","composition_change":"见 Markdown","visual_focus_analysis":"见 Markdown","balance_analysis":"见 Markdown","proportion_analysis":"见 Markdown","direction_analysis":"见 Markdown","blank_space_analysis":"见 Markdown","layer_order_analysis":"见 Markdown","spatial_relationship_analysis":"见 Markdown","learning_explanation":md,"suggestions":["参考上方建议"],"fallback_used":False,"model_error":None}
        except Exception as e:
            return CompositionAnalyzeService._fallback(payload, str(e))
