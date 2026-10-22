"""Compile owned benchmark ability assets; no media, model calls or benchmark QA.

--write updates only the three generated config files below, atomically per file.
Without --write, compare committed assets against the definitions and fail on drift.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_sft_builder.util import write_json

OWNER='scripts/build_benchmark_recipe.py'
DOMAINS=['学术活动与栏目','软件开发','数学','人工智能大模型','计算存储与新跑','通信与网络',
         '学者访谈','交叉新兴领域','行业战略与商业洞察','网络与信息安全','电子与电磁工程',
         '材料化学与生物能源','智能终端','多媒体与图形图像','前沿探索与科普','质量与制造工程','智能汽车']

# Four original question intents per operation. No benchmark questions/answers are
# copied into the runtime. Placeholders must be instantiated from available evidence.
PATTERNS={
 'scene_recognition': [('根据{context}的环境特征，画面处于什么类型的场景？','What kind of setting is shown by the environmental features in {context}?'),
                       ('{context}中哪些环境细节能确定{focus}所在的场所类型？','Which environmental details in {context} establish the type of place containing {focus}?'),
                       ('{context}呈现的空间环境与{criterion}有什么关系？','How does the setting visible in {context} relate to {criterion}?'),
                       ('请说明{context}中{focus}周围的可见环境。','Describe the visible surroundings of {focus} in {context}.')],
 'entity_identification': [('在{context}中，{focus}对应哪类可见对象？','What kind of visible object is {focus} in {context}?'),
                           ('根据{criterion}这一视觉线索，{context}中的目标对象是什么？','Which object in {context} is identified by the visual cue {criterion}?'),
                           ('{context}里与{focus}发生接触的对象是什么？','What object interacts with {focus} in {context}?'),
                           ('{context}中承担{criterion}作用的是哪个可见对象？','Which visible object serves the role {criterion} in {context}?')],
 'attribute_identification': [('在{context}中，{focus}的{criterion}是什么？','What is the {criterion} of {focus} in {context}?'),
                              ('根据{context}的清晰画面，描述{focus}的{criterion}。','Describe the {criterion} of {focus} from the clear view in {context}.'),
                              ('{context}里，{focus}具有哪项可辨认的外观特征？','Which observable appearance feature does {focus} have in {context}?'),
                              ('以{criterion}为观察重点，{context}中的{focus}是什么样的？','With attention to {criterion}, what does {focus} look like in {context}?')],
 'action_recognition': [('在{context}中，{focus}正在进行什么操作？','What operation does {focus} perform in {context}?'),
                        ('{context}里，{focus}如何处理{criterion}？','How does {focus} handle {criterion} in {context}?'),
                        ('根据{context}的动作过程，{focus}做了什么？','What does {focus} do in the action sequence shown in {context}?'),
                        ('{context}中，{focus}与{criterion}之间发生什么动作交互？','What action takes place between {focus} and {criterion} in {context}?')],
 'identify': [('在{context}中，{focus}有哪些可辨认的特征？','What observable features distinguish {focus} in {context}?'),
              ('根据{context}的画面，{focus}呈现什么状态？','What state does {focus} exhibit in {context}?'),
              ('{context}中的哪些表现能确定{focus}的身份或属性？','Which visible details establish the identity or property of {focus} in {context}?'),
              ('请描述{context}里与{criterion}有关的{focus}。','Describe {focus} in {context} with respect to {criterion}.')],
 'spatial_relation': [('以{context}为参照，{focus}处于什么相对位置？','Where is {focus} relative to {context}?'),
                      ('从{context}的视角看，{focus}之间的空间关系是什么？','From the viewpoint of {context}, how are {focus} spatially related?'),
                      ('{focus}与{context}的布局如何支持{criterion}？','How does the arrangement of {focus} and {context} support {criterion}?'),
                      ('在{context}中，{focus}沿哪个可见方向移动？','In {context}, in which visible direction does {focus} move?')],
 'sequence_ordering': [('将{context}中的{focus}按实际出现顺序排列。','Arrange {focus} in their observed order in {context}.'),
                       ('{context}中，{focus}各阶段的正确先后顺序是什么？','What is the correct stage order of {focus} in {context}?'),
                       ('依据{context}，请还原{focus}的操作顺序。','Reconstruct the demonstrated order of {focus} from {context}.'),
                       ('{context}里，{focus}首次出现的顺序是什么？','In what order do {focus} first appear in {context}?')],
 'state_change': [('对比{context}的前后画面，{focus}发生什么变化？','What changes in {focus} between the earlier and later views in {context}?'),
                  ('{context}中，{focus}从什么状态变为什么状态？','From what state to what state does {focus} change in {context}?'),
                  ('{focus}在{context}的哪方面出现明显转变？','Which property of {focus} visibly changes in {context}?'),
                  ('依据{context}，描述{focus}在{criterion}方面的变化。','Describe the change in {criterion} of {focus} using {context}.')],
 'comparison': [('比较{context}中的{focus}，它们在{criterion}方面有什么区别？','How do {focus} in {context} differ with respect to {criterion}?'),
                ('在{context}中，{focus}前后的共同点和差异是什么？','What similarities and differences are visible between the two instances of {focus} in {context}?'),
                ('以{criterion}为标准，{context}里的{focus}哪一处不同？','Under the criterion {criterion}, what distinguishes the instances of {focus} in {context}?'),
                ('{context}中两次出现的{focus}应如何对比？','How should the two appearances of {focus} in {context} be compared?')],
 'causal_link': [('{context}中，什么可见作用使{focus}发生变化？','What visible intervention causes the change in {focus} in {context}?'),
                 ('结合{context}的前因和结果，为什么{focus}出现{criterion}？','Using the observed cause and effect in {context}, why does {focus} show {criterion}?'),
                 ('{context}中哪个事件解释了{focus}随后的结果？','Which event in {context} explains the subsequent outcome for {focus}?'),
                 ('根据{context}，{focus}的结果与哪项操作有直接联系？','According to {context}, which operation is directly linked to the outcome of {focus}?')],
 'synopsis': [('整段{context}围绕{focus}展示了什么主要过程？','What main process involving {focus} is demonstrated across {context}?'),
              ('结合关键画面，概括{context}的主要内容。','Summarize the main content of {context} using the salient visual evidence.'),
              ('{context}中有哪些阶段共同构成了{focus}？','Which stages together constitute {focus} in {context}?'),
              ('根据多个片段，{context}主要展示了{focus}的哪方面？','Across its segments, which aspect of {focus} does {context} mainly demonstrate?')],
 'qualitative_motion': [('{context}中，{focus}的运动趋势如何变化？','How does the motion of {focus} change qualitatively in {context}?'),
                        ('比较{context}的前后状态，{focus}的运动有什么特点？','What characterizes the earlier versus later motion of {focus} in {context}?'),
                        ('{context}里，{focus}是如何从运动转为另一种状态的？','How does {focus} transition between motion states in {context}?'),
                        ('用定性描述说明{context}中{focus}的{criterion}。','Qualitatively describe the {criterion} of {focus} in {context}.')],
 'composition': [('结合{context}中的两处线索，如何确定{focus}？','How do the two clues in {context} jointly establish {focus}?'),
                 ('只有同时考虑{context}的不同观察，才能得出关于{focus}的什么结论？','What conclusion about {focus} requires combining the distinct observations in {context}?'),
                 ('{context}中的{criterion}与{focus}有什么关系？','What relationship connects {criterion} and {focus} across the observations in {context}?'),
                 ('把{context}中关于{focus}的线索联系起来，能得到什么答案？','What answer follows from linking the clues about {focus} in {context}?')],
 'interaction': [('{context}里，{focus}的可见协作方式如何变化？','How does the observable collaboration of {focus} change in {context}?'),
                 ('比较{context}的两个阶段，{focus}如何回应对方的动作？','Across two stages of {context}, how does {focus} respond to the other participant’s actions?'),
                 ('从{context}的行动顺序看，{focus}各承担什么可见角色？','What observable roles do {focus} take in the action sequence of {context}?'),
                 ('根据{context}，{focus}的互动由哪种行为转向哪种行为？','According to {context}, between which observable behaviors does the interaction of {focus} shift?')],
 'turning_point': [('{context}中，哪个可见事件改变了{focus}的进程？','Which observable event changes the course of {focus} in {context}?'),
                   ('联系转折前后画面，{context}的关键转折是什么？','Considering the before and after scenes, what is the pivotal event in {context}?'),
                   ('{context}中{focus}的局面为何在{criterion}之后发生变化？','Why does the situation of {focus} change after {criterion} in {context}?'),
                   ('什么事件使{context}里的{focus}进入下一阶段？','What event moves {focus} into the next stage of {context}?')],
 'anomaly': [('对比前后状态，{context}中的{focus}出现了什么明显异常？','What visible inconsistency appears in {focus} when comparing the states in {context}?'),
             ('{context}中{focus}的哪项变化与此前状态不一致？','Which change in {focus} conflicts with its earlier visible state in {context}?'),
             ('请依据画面描述{context}里{focus}的反常表现。','Describe the visually unusual behavior of {focus} in {context}.'),
             ('从{context}给出的线索看，{focus}的异常发生在哪里？','Where does the visible anomaly involving {focus} occur in {context}?')],
 'apply_demo': [('将{context}示范的方法用于{focus}时，哪个步骤需要按{criterion}调整？','When applying the demonstrated method in {context} to {focus}, which step must change under {criterion}?'),
                ('对照{context}，{focus}的做法与示范在哪一步不一致？','At which step does the described approach to {focus} differ from the demonstration in {context}?'),
                ('根据{context}演示的流程，{focus}接下来应执行什么操作？','Following the procedure demonstrated in {context}, what operation should come next for {focus}?'),
                ('{context}中哪项操作约束说明{focus}的方案需要修改？','Which demonstrated constraint in {context} shows that the proposed approach to {focus} needs revision?')],
 'retrieval': [('在整段{context}中找到{focus}的片段，该处展示了什么？','Find the occurrence of {focus} in the full {context}; what is shown there?'),
               ('整段{context}里，在{criterion}之后出现的{focus}有什么特征？','Across the full {context}, what characterizes the occurrence of {focus} after {criterion}?'),
               ('结合整段{context}的上下文，{focus}当时进行了什么操作？','Within the context of the full {context}, what operation does {focus} perform at the relevant moment?'),
               ('在整段{context}里检索{criterion}，该处的{focus}是什么状态？','Locate {criterion} within the full {context}; what state is {focus} in at that point?')],
 'coarse_location': [('{focus}发生在整段{context}的哪个已有粗时间范围内？','Within which supported coarse time range of the full {context} does {focus} occur?'),
                     ('依据{context}的事件索引，定位{focus}所在的片段。','Using the event context of {context}, locate the segment containing {focus}.'),
                     ('整段{context}里，{criterion}对应哪个时间段？','Which supported time interval in the full {context} corresponds to {criterion}?'),
                     ('请指出{context}中展示{focus}的已有时间窗口。','Identify the existing supported time window showing {focus} in {context}.')],
 'timeline': [('按可支持的粗时间段整理整段{context}中{focus}的事件线。','Organize the events of {focus} across the full {context} into a supported coarse timeline.'),
              ('整段{context}里，{focus}依次经历哪些主要阶段？','Which major stages does {focus} pass through, in order, across the full {context}?'),
              ('请还原整段{context}中{focus}从开始到结束的事件进程。','Reconstruct the progression of {focus} from beginning to end across {context}.'),
              ('联系不同片段，给出{context}里{focus}的主要事件顺序与粗范围。','Connect the segments to give the main event order and coarse ranges for {focus} in {context}.')],
 'hierarchical_summary': [('分开始、中间和结束概括整段{context}中{focus}的进展。','Summarize the development of {focus} across the beginning, middle, and end of the full {context}.'),
                          ('整段{context}的主要阶段如何共同组成{focus}的完整过程？','How do the major stages of the full {context} form the complete process of {focus}?'),
                          ('请按阶段组织整段{context}的关键内容，并说明阶段间的联系。','Organize the salient content of the full {context} by stage and explain the connections.'),
                          ('结合开头、过程和结局，说明整段{context}的整体结构。','Describe the overall structure of the full {context} using its opening, development, and conclusion.')],
 'knowledge_concept': [('根据{context}中{focus}的可见特征，应归为哪个专业概念？','Which domain concept best describes the visible features of {focus} in {context}?'),
                       ('{context}中{focus}展示的是哪一种原理或方法？','Which principle or method is illustrated by {focus} in {context}?'),
                       ('{context}里哪些观察特征能区分{focus}与相近概念？','Which observed features in {context} distinguish {focus} from a closely related concept?'),
                       ('结合专业知识，如何解释{context}中{focus}的概念归属？','Using domain knowledge, how should the observed {focus} in {context} be classified?')],
 'knowledge_mechanism': [('结合{context}的可见变化，什么机制解释{focus}？','Which domain mechanism explains {focus} given the visible changes in {context}?'),
                         ('{context}中{focus}的表现为什么符合{criterion}所涉及的机制？','Why does the observed behavior of {focus} in {context} follow the mechanism relevant to {criterion}?'),
                         ('根据{context}的观察条件，{focus}的结果由什么原理导致？','Under the conditions observed in {context}, which principle explains the outcome for {focus}?'),
                         ('{context}中哪些特征支持对{focus}的机制解释？','Which observed features in {context} support the mechanism explaining {focus}?')],
 'knowledge_method': [('针对{context}中{focus}的实际条件，哪种方法最适用？','Which method best fits the observed conditions of {focus} in {context}?'),
                      ('根据{context}展示的方法，{focus}在{criterion}条件下应如何处理？','Using the method illustrated in {context}, how should {focus} be handled under {criterion}?'),
                      ('{context}的观察说明，解决{focus}时必须满足哪项适用条件？','Which applicability condition for handling {focus} is established by the observations in {context}?'),
                      ('联系{context}的可见操作，{focus}应选择哪项方法及理由？','Considering the visible operation in {context}, which method should be selected for {focus}, and why?')],
 'knowledge_condition': [('比较{context}中的两种可见条件，{focus}为何表现不同？','Why does {focus} behave differently under the two conditions observed in {context}?'),
                         ('如果仅改变题干给出的{criterion}，相对{context}的观察基线，{focus}会有何定性变化？','If only the explicitly stated condition {criterion} changes, how would {focus} change qualitatively relative to the observed baseline in {context}?'),
                         ('{context}中哪项条件区别决定了{focus}适用的专业规则？','Which observed condition difference in {context} determines the domain rule applicable to {focus}?'),
                         ('依据{context}的对照观察，如何判断{focus}在{criterion}下的结果？','Using the comparative observations in {context}, how should the outcome of {focus} under {criterion} be assessed?')],
 'knowledge_diagnosis': [('{context}中{focus}的可见异常最支持哪一种原因？','Which cause is best supported by the visible abnormality of {focus} in {context}?'),
                         ('结合{context}的观察，哪项证据能区分{focus}的不同故障解释？','Which observation in {context} distinguishes competing explanations for the failure of {focus}?'),
                         ('根据{context}展示的条件和结果，{focus}的问题应如何解释？','How should the problem with {focus} be explained from the observed conditions and outcome in {context}?'),
                         ('{context}的哪些可见表现支持对{focus}的判断？','Which visible features in {context} support the diagnosis of {focus}?')],
 'knowledge_rationale': [('{context}中针对{focus}执行该操作的专业理由是什么？','What domain rationale explains the operation performed on {focus} in {context}?'),
                         ('联系{context}的操作前后状态，为什么{focus}需要{criterion}？','Considering the before and after states in {context}, why does {focus} require {criterion}?'),
                         ('根据{context}观察到的条件，{focus}这一步的作用是什么？','Given the conditions observed in {context}, what purpose does this step serve for {focus}?'),
                         ('哪项专业原理能说明{context}中{focus}的操作选择？','Which domain principle explains the operational choice for {focus} in {context}?')],
}


def task(name,branch,op,title,roles,min_facts=1,min_windows=1,forms=('oe','mcq'),*,global_coverage=False,answer=None):
    checks=['operation_match','caption_faithfulness','video_necessity','answer_contract']
    if op in ('causal_link','composition','turning_point','apply_demo') or branch=='knowledge':
        checks.append('reasoning_validity')
    if branch=='knowledge': checks.append('knowledge_rule_validity')
    if op in ('retrieval','coarse_location'): checks.append('retrieval_scope')
    mistakes={
      'scene_recognition':['scene_confusion','scope_mismatch','evidence_mismatch'],
      'entity_identification':['entity_swap','category_confusion','evidence_mismatch'],
      'attribute_identification':['attribute_swap','entity_swap','evidence_mismatch'],
      'action_recognition':['action_confusion','participant_swap','evidence_mismatch'],
      'spatial_relation':['relation_reversal','reference_frame_confusion','entity_swap'],
      'state_change':['state_inversion','entity_swap','temporal_swap'],
      'comparison':['criterion_mismatch','state_inversion','entity_swap'],
      'causal_link':['causal_reversal','unsupported_cause','evidence_mismatch'],
      'composition':['premise_omission','relation_swap','evidence_mismatch'],
      'synopsis':['salience_distortion','scope_mismatch','evidence_mismatch'],
      'qualitative_motion':['direction_reversal','motion_state_confusion','entity_swap'],
      'interaction':['participant_swap','response_reversal','evidence_mismatch'],
      'turning_point':['cause_outcome_confusion','consequence_mismatch','evidence_mismatch'],
      'anomaly':['baseline_confusion','state_inversion','evidence_mismatch'],
      'apply_demo':['step_swap','constraint_violation','rule_misapplication'],
      'retrieval':['occurrence_swap','entity_swap','scope_mismatch'],
      'coarse_location':['scope_mismatch'], 'sequence_ordering':['temporal_swap'],
      'knowledge_concept':['concept_confusion','evidence_mismatch','condition_violation'],
      'knowledge_mechanism':['mechanism_confusion','causal_reversal','condition_violation'],
      'knowledge_method':['rule_misapplication','condition_violation','method_confusion'],
      'knowledge_condition':['condition_violation','rule_misapplication','outcome_reversal'],
      'knowledge_diagnosis':['cause_confusion','discriminating_evidence_omission','condition_violation'],
      'knowledge_rationale':['purpose_confusion','rule_misapplication','condition_violation'],
    }
    return dict(name=name,branch=branch,family='domain_reasoning' if branch=='knowledge' else
                'long_context_understanding' if branch=='long' else 'video_ability',
                status='proposed_enabled',contract_version=1,operation=op,title_zh=title,
                minimum_fact_count=min_facts,minimum_windows=min_windows,role_groups=roles,
                question_types=list(forms),global_coverage=global_coverage,
                answer_contract=answer or title+'；答案须完整执行所问操作，不得退化为主体或动作识别',
                required_capability_checks=checks,
                evidence_requirement='只使用caption明确记录的原片观察；角色组各引用必要fact_id，不同角色组不得复用同一事实',
                knowledge_policy='domain_rule_plus_essential_observations' if branch=='knowledge' else 'observed_or_demonstrated_relation_only',
                allowed_distractor_types=mistakes.get(op,['scope_mismatch','evidence_mismatch']))


def definitions():
    return [
      task('scene_description','general','scene_recognition','场景与环境识别',{'target_observation':1},answer='说明有视觉证据的场景类型/环境，不猜地名、身份或隐含故事'),
      task('entity_identification','general','entity_identification','实体类别与目标识别',{'target_observation':1},answer='识别实际对象类别或可见身份描述，不猜未提供的姓名、国籍或职业背景'),
      task('entity_attribute','general','attribute_identification','实体可见属性识别',{'target_observation':1},answer='只回答被询问的可见属性；不得改答动作或对象名称'),
      task('spatial_relation','general','spatial_relation','参照系下空间关系',{'spatial_configuration':1}),
      task('action_description','general','action_recognition','动作与操作识别',{'target_observation':1},answer='回答明确动作、参与对象或操作，不用衣着替代动作答案'),
      task('event_order','general','sequence_ordering','事件与操作顺序',{'ordered_events':3},3,answer='必须提供ordering，程序打乱事件并生成正确序列；不止识别一个动作'),
      task('state_change','general','state_change','同一实体状态/存在变化',{'before':1,'after':1},2),
      task('temporal_comparison','general','comparison','不同阶段的对照',{'case_a':1,'case_b':1},2),
      task('observable_causality','general','causal_link','可见干预与因果结果',{'cause':1,'effect':1},2,answer='给出观察支持的作用和结果；时间先后不是充分因果证据'),
      task('video_synopsis','general','synopsis','多观察支持的主旨与过程',{'salient_observations':2},2,2,answer='概括主旨并包含关键观察/过程；不能只有通用主题词'),
      task('qualitative_motion','general','qualitative_motion','定性运动趋势',{'motion_observations':2},2,answer='说明运动状态/方向/快慢趋势；不输出速度、轨迹坐标或精确周期'),
      task('object_appearance_order','general','sequence_ordering','实体首次出现顺序',{'ordered_events':3},3,answer='实体身份清晰且首次出现有证据；必须ordering，禁止数总次数'),
      task('scene_transition','general','state_change','场景与环境转换',{'before':1,'after':1},2,answer='明确前后场景及转换关系，不用幻觉补拍摄地点'),
      task('compositional_relation','general','composition','多事实关系组合',{'premise_a':1,'premise_b':1},2,answer='答案必须同时使用两个不同事实，不能一处事实已直接给出答案'),
      task('visible_interaction','general','interaction','可见互动与协作变化',{'interaction_before':1,'interaction_after':1},2,answer='只说明行为回应、协作或可见角色变化，不猜人格、内心或对白'),
      task('narrative_turning_point','general','turning_point','有后果的事件转折',{'setup':1,'turning_event':1,'outcome':1},3,answer='指出转折事件并连接前后可见后果；不臆测隐喻、记忆或作者意图'),
      task('visual_anomaly','general','anomaly','可见异常与状态冲突',{'baseline':1,'observed_change':1},2,answer='报告可见反常变化，不编造魔术秘密、隐藏动作或不可见物理机制'),
      task('demonstrated_method_application','general','apply_demo','示范方法的定性迁移',{'demonstrated_method':2},2,answer='用视频明确示范的规则检查题干中显式给出的变式；不另发查询图片或精确数值求解'),
      task('long_context_retrieval','long','retrieval','长上下文单段信息检索',{'retrieval_evidence':1},answer='在整片上下文中辨识目标片段并回答；可仅一段答案证据，不是任意单帧题套Long标签'),
      task('segment_retrieval','long','coarse_location','事件的已有粗时间范围定位',{'located_event':1},answer='使用已有TIME窗口的粗范围，不捏造精确事件起止或时长'),
      task('long_state_comparison','long','comparison','跨段状态/情境对照',{'case_a':1,'case_b':1},2,2),
      task('cross_segment_qa','long','composition','跨段必要事实关联',{'premise_a':1,'premise_b':1},2,2),
      task('long_event_order','long','sequence_ordering','跨段事件顺序',{'ordered_events':3},3,3,answer='至少三个不同证据段的事件；必须ordering，由程序构建排序题'),
      task('long_causal_link','long','causal_link','跨段原因与后果关联',{'cause':1,'effect':1},2,2,answer='跨段因果两端均必要且有可见联系；不以先后顺序替代因果'),
      task('event_timeline','long','timeline','多阶段事件时间线',{'ordered_events':3},3,3,('oe',),answer='按至少三个事件的真实顺序给出过程及支持的粗时间范围，不能只列主题'),
      task('hierarchical_summary','long','hierarchical_summary','全片层级总结',{'salient_observations':3},3,3,('oe',),global_coverage=True,answer='组织开头、中间、结束的阶段及联系；不能一段摘要换三种说法'),
      task('knowledge_concept_identification','knowledge','knowledge_concept','观察到专业概念的识别',{'observed_phenomenon':1},answer='由必要视频特征选择概念/方法，不能只靠定义、领域标签或题干作答'),
      task('knowledge_mechanism_explanation','knowledge','knowledge_mechanism','现象的专业机制解释',{'conditions':1,'observed_result':1},2,answer='用适用的专业规则解释实际条件与结果，不能只复述看到的动作'),
      task('knowledge_method_application','knowledge','knowledge_method','证据条件下的方法应用',{'observed_conditions':1},answer='结合实际视频条件选择/应用专业方法；不生成无视频条件的教材题'),
      task('knowledge_condition_comparison','knowledge','knowledge_condition','条件差异与定性规则应用',{'baseline':1,'comparison_conditions':1},2,answer='对照已观察条件；假设变化必须在题干明确给出，不编造视频观测或精密数值'),
      task('knowledge_evidence_diagnosis','knowledge','knowledge_diagnosis','基于观察的原因/问题辨析',{'observed_signs':1,'discriminating_evidence':1},2,answer='证据足以区分相近原因时才给判断，缺精细影像/日志/读数或存在多解则弃答'),
      task('knowledge_procedure_rationale','knowledge','knowledge_rationale','专业操作的目的与原理',{'observed_operation':1,'observed_context':1},2,answer='解释这个视频条件下该操作的专业作用，不能变成泛化操作识别或领域常识'),
    ]


GENERAL_MAP={
 'Action Reasoning':['observable_causality','demonstrated_method_application','narrative_turning_point'],
 'Action Recognition':['action_description'], 'Attribute Perception':['entity_attribute'],
 'Information Synopsis':['video_synopsis'], 'Object Reasoning':['compositional_relation','observable_causality'],
 'Object Recognition':['entity_identification','scene_description'], 'Spatial Perception':['spatial_relation'],
 'Spatial Reasoning':['spatial_relation','compositional_relation'], 'Temporal Perception':['temporal_comparison','event_order'],
 'Temporal Reasoning':['event_order','state_change','temporal_comparison'],
 'Causal Reasoning':['observable_causality','narrative_turning_point'],
 'Collective Dynamics Analysis':['visible_interaction'], 'Dyadic Interaction Dynamics':['visible_interaction'],
 'Counterintuitive Comprehension':['visual_anomaly'],
 'Entity Attribute Change Detection':['state_change'], 'Entity Existence Change Detection':['state_change'],
 'Event Sequence Ordering':['event_order'], 'General Skills Acquisition':['demonstrated_method_application'],
 'High-Order Narrative Deconstruction':['narrative_turning_point'], 'Individual Social Cognition':['visible_interaction'],
 'Motion Properties Analysis':['qualitative_motion'], 'Narrative Cloze Inference':['narrative_turning_point'],
 'Narrative Turning Point Detection':['narrative_turning_point'], 'Object Appearance Ordering':['object_appearance_order'],
 'Professional Knowledge Acquisition':['demonstrated_method_application'],
 'Scene Transformation Detection':['scene_transition'], 'Spatial Understanding':['spatial_relation','compositional_relation'],
 'Visual Recognition':['scene_description','entity_identification','entity_attribute','action_description'],
}
LONG_MAP={
 'Action Reasoning':['long_causal_link','cross_segment_qa'], 'Action Recognition':['long_context_retrieval'],
 'Attribute Perception':['long_context_retrieval','long_state_comparison'],
 'Information Synopsis':['hierarchical_summary','event_timeline'], 'Object Reasoning':['cross_segment_qa'],
 'Object Recognition':['long_context_retrieval'], 'Spatial Perception':['long_context_retrieval'],
 'Spatial Reasoning':['cross_segment_qa'], 'Temporal Perception':['segment_retrieval'],
 'Temporal Reasoning':['long_event_order','event_timeline'],
 'entity recognition':['long_context_retrieval','long_state_comparison'],
 'event understanding':['long_context_retrieval','cross_segment_qa','event_timeline'],
 'key information retrieval':['long_context_retrieval'], 'reasoning':['cross_segment_qa','long_causal_link'],
 'summarization':['hierarchical_summary','event_timeline'], 'temporal grounding':['segment_retrieval'],
}


def compile_assets():
    tasks=definitions()
    knowledge=[t['name'] for t in tasks if t['branch']=='knowledge']
    names={t['name'] for t in tasks}
    templates=[]
    for t in tasks:
        for i,pair in enumerate(PATTERNS[t['operation']]):
            for lang,pattern in zip(('zh','en'),pair):
                templates.append(dict(template_id=f'b1_{t["name"]}_{lang}_{i:02d}',task=t['name'],language=lang,
                  supported_question_types=t['question_types'],question_style=t['operation']+f'_{i:02d}',
                  question_pattern=pattern,required_slots=sorted(set(re.findall(r'\{(\w+)\}',pattern))),
                  answer_contract=t['answer_contract'],distractor_types=t['allowed_distractor_types']))
    source=json.loads((ROOT/'docs/three_branch_reference_category_summary_2026-10-22.json').read_text(encoding='utf8'))
    coverage=[]
    partial={'Collective Dynamics Analysis','Dyadic Interaction Dynamics','Individual Social Cognition',
             'High-Order Narrative Deconstruction','Narrative Cloze Inference','Professional Knowledge Acquisition',
             'Counterintuitive Comprehension','General Skills Acquisition','Temporal Perception','temporal grounding'}
    for s in source:
        key=s['subclass']; targets=[]
        if s['status']!='deferred':
            targets=(GENERAL_MAP.get(key,[]) if s['branch']=='general' else LONG_MAP.get(key,[]) if s['branch']=='long' else knowledge)
        status='deferred' if not targets else 'partial_transfer' if key in partial or s['branch']=='knowledge' else 'caption_conditioned_transfer'
        coverage.append(dict(branch=s['branch'],benchmark=s['dataset'],subclass=key,source_count=s['source_count'],
          tasks=targets,status=status,limit=s['reason'] if s['status']=='deferred' else
          '只迁移可由当前视觉caption支持的操作；不覆盖对白、隐藏动机、符号精读、精确计数/计算或缺失查询图'))
        if not set(targets)<=names: raise ValueError('Unknown task in coverage')
    registry=dict(generated_by=OWNER,version=1,recipe='benchmark_v1',task_target='uniform_within_branch',
      source_context=dict(ranked_video_domains=DOMAINS,domains_are_tasks=False,
        use='fit阶段与模板意图的弱倾向，不作为证据/答案/学科硬配额；均衡阶段仍按能力task堆',
        knowledge_fit_preferences=['knowledge_concept_identification','knowledge_method_application',
          'knowledge_mechanism_explanation','knowledge_procedure_rationale'],
        forbidden_shortcuts=['从领域类别猜题与答案','只凭字幕/PPT标题解题','将访谈对白补成视频事实','把知识题写成纯教材常识题']),
      tasks=tasks)
    return {'benchmark_task_registry.json':registry,
            'benchmark_question_templates.json':dict(generated_by=OWNER,version=1,templates=templates),
            'benchmark_capability_coverage.json':dict(generated_by=OWNER,version=1,source_group_count=96,
               note='任务参考映射不是benchmark提分证明；不载入原测试QA',coverage=coverage)}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--write',action='store_true');a=p.parse_args()
    for name,value in compile_assets().items():
        path=ROOT/'configs'/name
        if a.write:
            if path.exists() and json.loads(path.read_text(encoding='utf8')).get('generated_by')!=OWNER:
                raise ValueError('Refusing to overwrite unowned asset: '+name)
            write_json(path,value,replace=True)
        elif not path.exists() or json.loads(path.read_text(encoding='utf8'))!=value:
            raise ValueError('Compiled asset drift: '+name)
    print('PASS: 32 tasks, 256 bilingual templates, 96 source-group mappings; no model calls')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
