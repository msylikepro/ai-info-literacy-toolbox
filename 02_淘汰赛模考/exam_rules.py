"""Validated per-user exam preferences and immutable paper scoring rules."""
from decimal import Decimal, InvalidOperation

KINDS=('single','multi','judge')
LABELS={'single':'单选','multi':'多选','judge':'判断'}
DEFAULT_TIMING={'personal':5,'team':15,'training_personal':0,'training_team':0,'simulation':20}

def validate_timing(timing):
    if not isinstance(timing,dict) or set(timing)!=set(DEFAULT_TIMING):
        raise ValueError('请完整填写五项答题时限')
    if any(type(value) is not int or not 0<=value<=1440 for value in timing.values()):
        raise ValueError('时限须为0至1440的整数分钟，0表示不限时')
    return dict(timing)

def defaults(mode):
    return {kind:dict(count=count,correct=4 if mode=='team' else 2,wrong=-1,unanswered=0)
            for kind,count in zip(KINDS,(6,2,2))}

def validate_profile(profile):
    if not isinstance(profile,dict) or set(profile)!=set(KINDS):
        raise ValueError('请完整设置单选、多选、判断三类题目')
    normalized={}
    for kind in KINDS:
        row=profile[kind]
        if not isinstance(row,dict) or set(row)!={'count','correct','wrong','unanswered'}:
            raise ValueError(LABELS[kind]+'题设置不完整')
        count=row['count']
        if type(count) is not int or not 0<=count<=500:
            raise ValueError('题数须为0至500的整数')
        item={'count':count}
        for key in ('correct','wrong','unanswered'):
            value=row[key]
            if type(value) not in (int,float):
                raise ValueError('分值须为数字')
            try: amount=Decimal(str(value))
            except InvalidOperation: raise ValueError('分值格式无效')
            if not amount.is_finite() or not -1000<=amount<=1000 or amount!=amount.quantize(Decimal('.01')):
                raise ValueError('分值须在-1000至1000之间，最多两位小数')
            item[key]=float(amount)
        if item['correct']<0 or max(item['wrong'],item['unanswered'])>item['correct']:
            raise ValueError('答对得分不能为负，答错和未答得分不能高于答对得分')
        normalized[kind]=item
    if not 1<=sum(row['count'] for row in normalized.values())<=500:
        raise ValueError('每份试卷总题数须为1至500题')
    return normalized

def validate_settings(settings):
    if not isinstance(settings,dict) or set(settings)!={'personal','team'}:
        raise ValueError('请同时提交个人和团队两套完整设置')
    return {mode:validate_profile(settings[mode]) for mode in ('personal','team')}

def outcome(chosen,correct):
    return 'unanswered' if not chosen else ('correct' if set(chosen)==set(correct) else 'wrong')

def total(values):
    return float(sum((Decimal(str(value)) for value in values),Decimal(0)))
