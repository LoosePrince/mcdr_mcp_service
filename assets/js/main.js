/**
 * MCDR MCP Service 页面缓存系统
 * 预加载其他页面并缓存，提高页面切换速度
 */

// 缓存版本控制，当修改页面结构时修改此版本号使缓存失效
const CACHE_VERSION = '1.0.0';

// 需要缓存的页面
const PAGES_TO_CACHE = [
  'index.html',
  'install.html',
  'docs.html'
];

// 当前页面URL
const currentPage = window.location.pathname.split('/').pop() || 'index.html';

// 初始化
document.addEventListener('DOMContentLoaded', () => {
  // 初始化缓存系统
  initCacheSystem();
  
  // 拦截导航链接点击
  interceptNavLinks();
});

/**
 * 初始化缓存系统
 */
function initCacheSystem() {
  // 检查缓存版本
  const storedVersion = localStorage.getItem('mcdr_cache_version');
  
  // 如果版本不匹配，清除所有缓存
  if (storedVersion !== CACHE_VERSION) {
    clearAllCache();
    localStorage.setItem('mcdr_cache_version', CACHE_VERSION);
  }
  
  // 预加载其他页面
  preloadPages();
}

/**
 * 预加载页面
 */
function preloadPages() {
  // 只加载不是当前页面的其他页面
  PAGES_TO_CACHE.forEach(page => {
    if (page !== currentPage) {
      // 使用较低优先级加载，避免影响当前页面性能
      setTimeout(() => {
        fetchAndCachePage(page);
      }, 2000); // 延迟2秒加载，优先处理当前页面
    }
  });
}

/**
 * 获取并缓存页面
 * @param {string} pageUrl - 页面URL
 */
function fetchAndCachePage(pageUrl) {
  // 检查缓存是否存在且未过期
  const cachedPage = localStorage.getItem(`mcdr_page_${pageUrl}`);
  const cachedTimestamp = localStorage.getItem(`mcdr_page_timestamp_${pageUrl}`);
  const now = new Date().getTime();
  
  // 如果缓存存在且未过期（24小时内）
  if (cachedPage && cachedTimestamp && (now - parseInt(cachedTimestamp)) < 24 * 60 * 60 * 1000) {
    console.log(`页面 ${pageUrl} 已从缓存加载`);
    return;
  }
  
  // 获取页面内容
  fetch(pageUrl)
    .then(response => {
      if (!response.ok) {
        throw new Error(`无法加载页面: ${pageUrl}`);
      }
      return response.text();
    })
    .then(html => {
      // 提取页面主体内容
      const content = extractMainContent(html);
      
      // 存储到本地缓存
      try {
        localStorage.setItem(`mcdr_page_${pageUrl}`, content);
        localStorage.setItem(`mcdr_page_timestamp_${pageUrl}`, now.toString());
        console.log(`页面 ${pageUrl} 已缓存`);
      } catch (e) {
        // 存储空间不足时清除旧缓存
        console.warn('缓存存储失败，正在清理旧缓存', e);
        clearOldCache();
      }
    })
    .catch(error => {
      console.error('预加载页面失败:', error);
    });
}

/**
 * 从HTML中提取主要内容
 * @param {string} html - 完整HTML
 * @return {string} - 提取的主要内容
 */
function extractMainContent(html) {
  // 创建临时DOM解析HTML
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  
  // 提取主体内容（这里我们缓存整个页面，因为需要完整替换）
  return html;
}

/**
 * 拦截导航链接点击
 */
function interceptNavLinks() {
  // 获取所有导航链接
  const navLinks = document.querySelectorAll('nav a');
  
  navLinks.forEach(link => {
    // 只拦截内部页面链接
    const href = link.getAttribute('href');
    if (href && PAGES_TO_CACHE.includes(href)) {
      link.addEventListener('click', function(e) {
        // 检查是否有缓存
        const cachedContent = localStorage.getItem(`mcdr_page_${href}`);
        
        // 如果有缓存，使用缓存内容
        if (cachedContent) {
          e.preventDefault();
          
          // 记录当前滚动位置到历史状态
          const currentScroll = window.scrollY;
          history.replaceState({ scrollY: currentScroll }, '');
          
          // 更新浏览器历史
          history.pushState({ fromCache: true }, '', href);
          
          // 直接替换页面内容
          document.open();
          document.write(cachedContent);
          document.close();
          
          // 通知用户使用了缓存
          console.log(`从缓存加载页面: ${href}`);
          
          // 重新获取最新内容并更新缓存
          setTimeout(() => {
            fetchAndCachePage(href);
          }, 1000);
        }
      });
    }
  });
  
  // 处理浏览器后退/前进
  window.addEventListener('popstate', function(e) {
    if (e.state && e.state.scrollY) {
      // 恢复滚动位置
      setTimeout(() => {
        window.scrollTo(0, e.state.scrollY);
      }, 100);
    }
  });
}

/**
 * 清除所有缓存
 */
function clearAllCache() {
  Object.keys(localStorage).forEach(key => {
    if (key.startsWith('mcdr_page_')) {
      localStorage.removeItem(key);
    }
  });
  console.log('所有页面缓存已清除');
}

/**
 * 清除旧缓存
 */
function clearOldCache() {
  // 获取所有缓存项及其时间戳
  const cacheItems = [];
  
  Object.keys(localStorage).forEach(key => {
    if (key.startsWith('mcdr_page_') && !key.includes('timestamp')) {
      const pageUrl = key.replace('mcdr_page_', '');
      const timestamp = localStorage.getItem(`mcdr_page_timestamp_${pageUrl}`);
      
      if (timestamp) {
        cacheItems.push({
          pageUrl,
          timestamp: parseInt(timestamp)
        });
      }
    }
  });
  
  // 按时间戳排序
  cacheItems.sort((a, b) => a.timestamp - b.timestamp);
  
  // 删除最旧的一半缓存
  const itemsToRemove = Math.ceil(cacheItems.length / 2);
  
  for (let i = 0; i < itemsToRemove; i++) {
    const { pageUrl } = cacheItems[i];
    localStorage.removeItem(`mcdr_page_${pageUrl}`);
    localStorage.removeItem(`mcdr_page_timestamp_${pageUrl}`);
    console.log(`已清除旧缓存: ${pageUrl}`);
  }
}