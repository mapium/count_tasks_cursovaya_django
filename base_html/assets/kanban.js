(function () {
    "use strict";

    function initDragAndDrop() {
        const tasks = document.querySelectorAll(".task-card");
        const columns = document.querySelectorAll(".kanban-column");
        if (!tasks.length || !columns.length) return;

        let draggedCard = null;
        tasks.forEach(function (task) {
            task.addEventListener("dragstart", function () {
                draggedCard = task;
                task.style.opacity = "0.6";
            });
            task.addEventListener("dragend", function () {
                task.style.opacity = "1";
            });
        });

        columns.forEach(function (column) {
            const container = column.querySelector(".kanban-tasks");
            if (!container) return;

            container.addEventListener("dragover", function (event) {
                event.preventDefault();
            });

            container.addEventListener("drop", function () {
                if (!draggedCard) return;
                container.appendChild(draggedCard);

                const taskId = draggedCard.dataset.id;
                const nextStatus = column.dataset.status;
                if (taskId && window.ApiClient?.tasks?.updateStatus) {
                    window.ApiClient.tasks.updateStatus(taskId, { status: nextStatus }).catch(function () {});
                }
            });
        });
    }

    document.addEventListener("DOMContentLoaded", initDragAndDrop);
})();
