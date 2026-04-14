(function () {
    "use strict";

    const roleOrder = [
        "Администратор",
        "Руководитель предприятия",
        "Руководитель подразделения",
        "Работник"
    ];

    function initRoleSwitcher() {
        const badge = document.getElementById("roleBadge");
        const btn = document.getElementById("switchRoleBtn");
        if (!badge || !btn) return;

        let index = 0;
        btn.addEventListener("click", function () {
            index = (index + 1) % roleOrder.length;
            badge.textContent = roleOrder[index];
        });
    }

    function initEmployeeFuzzySearch() {
        const input = document.getElementById("employeeSearch");
        if (!input) return;

        const cards = Array.from(document.querySelectorAll(".employee-card"));
        input.addEventListener("input", function () {
            const query = input.value.trim().toLowerCase();
            cards.forEach(function (card) {
                const name = (card.querySelector("h4")?.textContent || "").toLowerCase();
                card.style.display = !query || name.includes(query) ? "grid" : "none";
            });
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        initRoleSwitcher();
        initEmployeeFuzzySearch();
    });
})();
