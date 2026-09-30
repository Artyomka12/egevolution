/* Shared navigation: outside click and Escape. */
(function () {
    'use strict';
    var menu = document.getElementById('platformMenu');
    if (!menu) return;
    document.addEventListener('click', function (event) {
        if (!menu.contains(event.target) || event.target.closest('.nh-menu-panel a')) menu.open = false;
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && menu.open) {
            menu.open = false;
            menu.querySelector('summary').focus();
        }
    });

})();
