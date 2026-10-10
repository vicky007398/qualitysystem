(() => {
  const screen = document.querySelector('[data-welcome-screen]');
  const login = document.querySelector('[data-login-shell]');
  if (!screen || !login) return;
  const key = 'xyz-solar-welcome-seen';
  try { if (sessionStorage.getItem(key)) return; } catch (_) { /* Storage may be unavailable. */ }
  let finished = false;
  screen.hidden = false;
  login.inert = true;
  const skip = screen.querySelector('[data-welcome-skip]');
  skip.focus({preventScroll: true});
  const dismiss = () => {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    try { sessionStorage.setItem(key, '1'); } catch (_) { /* Sign-in still works without storage. */ }
    screen.classList.add('welcome-leaving');
    setTimeout(() => {
      screen.hidden = true;
      login.inert = false;
      login.querySelector('[name="employee"]')?.focus({preventScroll: true});
    }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 350);
  };
  const timer = setTimeout(dismiss, 4150);
  skip.addEventListener('click', dismiss);
  screen.addEventListener('keydown', event => {
    if (event.key === 'Escape') dismiss();
    if (event.key === 'Tab') { event.preventDefault(); skip.focus(); }
  });
})();
