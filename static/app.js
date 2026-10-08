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
