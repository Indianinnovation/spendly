// main.js — shared JavaScript for every page.

// Forms with data-confirm ask before submitting (used by delete buttons).
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
        if (!confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});
