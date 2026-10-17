// Set darkmode
document.getElementById('mode').addEventListener('click', () => {

    document.body.classList.toggle('dark');
    localStorage.setItem('theme', document.body.classList.contains('dark') ? 'dark' : 'light');
  
});

// Keep the mobile navigation available to keyboard users and announce its state.
var menuToggle = document.querySelector('.menu-toggle');
if (menuToggle) {
    menuToggle.addEventListener('click', () => {
        var expanded = menuToggle.getAttribute('aria-expanded') === 'true';
        menuToggle.setAttribute('aria-expanded', String(!expanded));
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && menuToggle.getAttribute('aria-expanded') === 'true') {
            menuToggle.setAttribute('aria-expanded', 'false');
            menuToggle.focus();
        }
    });
    document.getElementById('primary-navigation').addEventListener('click', (event) => {
        if (event.target.closest('a')) {
            menuToggle.setAttribute('aria-expanded', 'false');
        }
    });
}
  
// enforce local storage setting but also fallback to user-agent preferences
if (localStorage.getItem('theme') === 'dark' || (!localStorage.getItem('theme') && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
  
  document.body.classList.add('dark');
  
}
