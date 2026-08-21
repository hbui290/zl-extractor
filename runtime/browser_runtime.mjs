export const assertBrowserExpression = (expression) => {
  new Function(expression);
};

export const runtimeExceptionMessage = (details = {}) =>
  details.exception?.description || details.exception?.value || details.text || "runtime evaluation failed";
