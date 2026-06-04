(function (global) {
  'use strict';

  async function normalizeCompositionInput(rawData, options = {}) {
    const endpoint = options.endpoint || '/composition/validate-param-json';
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rawData),
    });
    let result;
    try {
      result = await response.json();
    } catch (error) {
      throw new Error(`JSON 清理接口返回了非 JSON 响应: ${error.message}`);
    }
    if (!response.ok) {
      const message = result?.message || `JSON 清理接口请求失败: HTTP ${response.status}`;
      const err = new Error(message);
      err.validation = result;
      throw err;
    }
    return {
      cleaned_json: result.document,
      document: result.document,
      validation: result,
      warnings: result.warnings || [],
      dropped_elements: result.dropped_elements || [],
      element_count: result.element_count || (result.document?.elements || []).length,
    };
  }

  global.normalizeCompositionInput = normalizeCompositionInput;
  global.sanitizeCompositionJson = normalizeCompositionInput;
})(window);
