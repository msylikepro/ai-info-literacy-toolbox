(()=>{
  const form=document.getElementById('exam-settings-form');
  if(!form)return;
  const modes={personal:'个人模式',team:'团队模式'},types={single:'单选',multi:'多选',judge:'判断'};
  const keys=['count','correct','wrong','unanswered'];
  const field=(mode,type,key)=>form.elements.namedItem(`${mode}.${type}.${key}`);
  const signature=()=>JSON.stringify([...form.querySelectorAll('input')].map(input=>input.value));
  const initial=signature(),status=document.getElementById('exam-settings-status'),error=document.getElementById('exam-settings-error');
  const timingForm=document.getElementById('exam-timing-form');
  const timeSignature=()=>JSON.stringify([...timingForm?.querySelectorAll('input')||[]].map(input=>input.value));
  const timingInitial=timeSignature(),rulesDirty=()=>signature()!==initial,timeDirty=()=>timeSignature()!==timingInitial;
  const draftKey='exam-settings-draft:'+document.getElementById('exam-settings').dataset.accountId;
  window.examRulesHasUnsavedChanges=()=>rulesDirty()||timeDirty();
  function preserveOtherDraft(otherForm,dirty){
    if(!otherForm||!dirty()){discardStoredDraft();return;}
    try{sessionStorage.setItem(draftKey,JSON.stringify({formId:otherForm.id,values:Object.fromEntries([...otherForm.querySelectorAll('input')].map(input=>[input.name,input.value]))}));}
    catch(reason){throw new Error('浏览器暂时无法保留另一组未保存的修改，请稍后重试。');}
  }
  function discardStoredDraft(){try{sessionStorage.removeItem(draftKey);}catch(reason){}}
  function restoreDraft(){
    try{
      const draft=JSON.parse(sessionStorage.getItem(draftKey)||'null');discardStoredDraft();
      const target=draft&&[form,timingForm].find(candidate=>candidate?.id===draft.formId);
      if(!target)return;
      for(const input of target.querySelectorAll('input'))if(typeof draft.values?.[input.name]==='string')input.value=draft.values[input.name];
      document.getElementById('exam-settings').open=true;
    }catch(reason){discardStoredDraft();}
  }
  function summary(){
    for(const mode of Object.keys(modes)){
      let count=0,max=0;
      for(const type of Object.keys(types)){const n=Number(field(mode,type,'count').value),correct=Number(field(mode,type,'correct').value);count+=n;max+=n*correct;}
      document.getElementById(`${mode}-rules-summary`).textContent=Number.isFinite(count)&&Number.isFinite(max)?`共 ${count} 题 · 满分 ${Number(max.toFixed(2))} 分`:'';
    }
    status.textContent=rulesDirty()?'有未保存的修改，请保存后再开始。':'已保存的设置用于新试卷。';
  }
  function readRules(){
    const result={};
    for(const [mode,label] of Object.entries(modes)){
      result[mode]={};let count=0;
      for(const [type,typeLabel] of Object.entries(types)){
        const rule={};
        for(const key of keys){
          const input=field(mode,type,key),raw=input.value.trim(),number=Number(raw),prefix=`${label}的${typeLabel}`;
          const reject=message=>{input.focus();throw new Error(prefix+message);};
          if(raw===''||!Number.isFinite(number))reject('请填写有效数字。');
          if(key==='count'){
            if(!Number.isInteger(number)||number<0||number>500)reject('题数须为 0–500 的整数。');
          }else{
            if(number<-1000||number>1000)reject('分值须在 −1000～1000 之间。');
            if(Math.abs(number*100-Math.round(number*100))>1e-8)reject('分值最多保留两位小数。');
          }
          rule[key]=number;
        }
        if(rule.correct<0){field(mode,type,'correct').focus();throw new Error(`${label}的${typeLabel}答对分不得为负数。`);}
        for(const key of ['wrong','unanswered'])if(rule[key]>rule.correct){field(mode,type,key).focus();throw new Error(`${label}的${typeLabel}${key==='wrong'?'答错':'未答'}分不得高于答对分。`);}
        result[mode][type]=rule;count+=rule.count;
      }
      if(count<1||count>500){field(mode,'single','count').focus();throw new Error(`${label}每卷总题数须为 1–500 题。`);}
    }
    return result;
  }
  form.addEventListener('input',summary);
  document.getElementById('exam-settings-reset').addEventListener('click',()=>{
    for(const mode of Object.keys(modes))for(const type of Object.keys(types)){
      const defaults={count:type==='single'?6:2,correct:mode==='team'?4:2,wrong:-1,unanswered:0};
      for(const key of keys)field(mode,type,key).value=defaults[key];
    }
    error.classList.add('hidden');summary();status.textContent='已恢复默认值，请点击保存后生效。';
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();error.classList.add('hidden');
    const submit=form.querySelector('[type=submit]'),inputs=[...form.querySelectorAll('input,button')];
    try{
      const settings=readRules();preserveOtherDraft(timingForm,timeDirty);inputs.forEach(input=>input.disabled=true);submit.textContent='正在保存…';
      const response=await fetch('/api/exam-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||'设置保存失败，请重试。');
      preserveOtherDraft(timingForm,timeDirty);location.reload();
    }catch(reason){discardStoredDraft();error.textContent=reason instanceof TypeError?'网络异常，设置尚未保存，请重试。':reason.message||'设置尚未保存，请重试。';error.classList.remove('hidden');}
    finally{inputs.forEach(input=>input.disabled=false);submit.textContent='保存题数与分值';}
  });
  if(timingForm){
    const timingLabels={personal:'个人对抗',team:'团队对抗',training_personal:'个人练习',training_team:'团队练习',simulation:'完整模拟总时限'};
    const timingDefaults={personal:5,team:15,training_personal:0,training_team:0,simulation:20};
    const timingError=document.getElementById('exam-timing-error'),timingStatus=document.getElementById('exam-timing-status');
    const timeField=mode=>timingForm.elements.namedItem('timing.'+mode);
    const timingSummary=()=>{timingStatus.textContent=timeDirty()?'有未保存的时间修改，请保存后再开始。':'时间设置独立保存，用于新试卷。';};
    timingForm.addEventListener('input',timingSummary);
    document.getElementById('exam-timing-reset').addEventListener('click',()=>{
      for(const [mode,minutes] of Object.entries(timingDefaults))timeField(mode).value=minutes;
      timingError.classList.add('hidden');timingSummary();timingStatus.textContent='已恢复默认时间，请点击保存后生效。';
    });
    timingForm.addEventListener('submit',async event=>{
      event.preventDefault();timingError.classList.add('hidden');
      const submit=timingForm.querySelector('[type=submit]'),inputs=[...timingForm.querySelectorAll('input,button')];
      try{
        const timing={};
        for(const [mode,label] of Object.entries(timingLabels)){
          const input=timeField(mode),raw=input.value.trim(),minutes=Number(raw);
          if(raw===''||!Number.isInteger(minutes)||minutes<0||minutes>1440){input.focus();throw new Error(label+'时间须为 0–1440 的整数（0 表示不限时）。');}
          timing[mode]=minutes;
        }
        preserveOtherDraft(form,rulesDirty);inputs.forEach(input=>input.disabled=true);submit.textContent='正在保存…';
        const response=await fetch('/api/exam-timing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(timing)});
        const data=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(data.error||'时间保存失败，请重试。');
        preserveOtherDraft(form,rulesDirty);location.reload();
      }catch(reason){discardStoredDraft();timingError.textContent=reason instanceof TypeError?'网络异常，时间尚未保存，请重试。':reason.message||'时间尚未保存，请重试。';timingError.classList.remove('hidden');}
      finally{inputs.forEach(input=>input.disabled=false);submit.textContent='保存答题时间';}
    });
    restoreDraft();timingSummary();
  }
  summary();
})();
