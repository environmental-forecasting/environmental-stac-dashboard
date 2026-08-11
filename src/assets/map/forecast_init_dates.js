/* Grey out calendar days that are not a forecast start.
   Allowed days are the init dates already sent to the picker. */
var dmcfuncs = window.dashMantineFunctions = window.dashMantineFunctions || {};

dmcfuncs.disableUnlessForecastInit = function (dateStr, options) {
  var allowed = options && options.allowed;
  return !allowed || !allowed[String(dateStr).slice(0, 10)];
};
