(() => {
  const toggle = document.querySelector('[data-sidebar-toggle]');
  toggle?.addEventListener('click', () => {
    if (window.innerWidth <= 760) document.body.classList.toggle('sidebar-open');
    else document.body.classList.toggle('sidebar-collapsed');
  });

  document.querySelectorAll('[data-delete-draft]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm('Delete this unsubmitted draft?')) event.preventDefault();
  }));

  document.querySelectorAll('[data-calculation-for]').forEach(output => {
    const input = document.querySelector(`[name="${output.dataset.calculationFor}"]`);
    if (!input) return;
    const update = () => {
      const value = Number(input.value);
      output.textContent = input.value && Number.isFinite(value) ? `Calculated: ${(value / 0.24).toFixed(3)} N/mm` : 'N/mm = Average N ÷ 0.24';
    };
    input.addEventListener('input', update);
    update();
  });
})();


(() => {
 const form = document.querySelector('[data-wizard]');
 if (!form) return;
 const steps = [...form.querySelectorAll('[data-checkpoint]')];
 const tabs = [...form.querySelectorAll('[data-step-go]')];
 let current = 0;
 const show = index => {
  current = Math.max(0, Math.min(steps.length - 1, index));
  steps.forEach((step, i) => { step.hidden = i !== current; step.classList.toggle('active', i === current); });
  tabs.forEach((tab,i) => { tab.classList.toggle('active',i===current); tab.setAttribute('aria-current',i===current?'step':'false'); });
  form.querySelector('[data-step-label]').textContent = `Checkpoint ${current+1} / ${steps.length}`;
  form.querySelector('[data-step-name]').textContent = steps[current].querySelector('h2').textContent;
  form.querySelector('[data-step-prev]').disabled = current === 0;
  form.querySelector('[data-step-next]').disabled = current === steps.length-1;
  tabs[current].scrollIntoView({block:'nearest',inline:'nearest',behavior:'smooth'});
 };
 const update = () => {
  let completed = 0;
  steps.forEach((step,i) => {const done=[...step.querySelectorAll('input,select')].every(input=>input.value.trim()!=='' && input.validity.valid);tabs[i].classList.toggle('complete',done);if(done) completed++;});
  form.querySelector('[data-completion]').textContent = `${completed} / ${steps.length} · ${Math.round(completed/steps.length*100)}% complete`;
  form.querySelector('[data-progress]').value=completed;
 };
 tabs.forEach((tab,i)=>tab.addEventListener('click',()=>show(i)));
 form.querySelector('[data-step-prev]').addEventListener('click',()=>show(current-1));
 form.querySelector('[data-step-next]').addEventListener('click',()=>show(current+1));
 form.addEventListener('input',update);form.addEventListener('change',update);
 // Reveal an invalid checkpoint before the browser tries to focus its field.
 form.addEventListener('invalid',event=>{const i=steps.findIndex(step=>step.contains(event.target));if(i>=0 && steps[i].hidden) show(i);},true);
 let touchX=null;
 const deck=form.querySelector('.checkpoint-deck');
 deck.addEventListener('touchstart',event=>{if(!event.target.closest('input,select,textarea'))touchX=event.changedTouches[0].clientX;},{passive:true});
 deck.addEventListener('touchend',event=>{if(touchX===null)return;const dx=event.changedTouches[0].clientX-touchX;if(Math.abs(dx)>70)show(current+(dx<0?1:-1));touchX=null;},{passive:true});
 show(0);update();
})();
