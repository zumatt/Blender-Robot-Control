window.setTheme = function (cssPath) {
    document.getElementById("theme-stylesheet").href = cssPath;
};

window.isDarkMode = function () {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
};
