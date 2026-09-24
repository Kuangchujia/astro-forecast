<?php
/**
 * 自动化：定时任务与数据新鲜度审计（指令 08 前半）
 *
 * ★ 必须先讲清的现实约束（不粉饰）：
 *   本插件的后台**跑不了 Python**，也就跑不了 skyfield 星历计算。
 *   因此「每月自动更新未来 12 个月天象」「每季度扩充历史数据集」这两件事，
 *   插件侧能做的只有三件：
 *     ① 按时**触发**并广播一个 action（`kcj_astro_need_recompute`），供有能力的
 *        站点（自建服务器 / 有 CI 的环境）挂回调去跑本地脚本；
 *     ② **审计**数据新鲜度（最新日记录 vs 今天），把结论写进 option；
 *     ③ 刷新插件自己的 transient 缓存。
 *   在 WordPress.com 托管环境下，真正的重算路径是：
 *     本机跑 `python/build_dataset.py --start ... --end ... --push`
 *     → 经 REST 端点 (kcj-astro/v1/import) 入库 → 服务端自动清缓存。
 *   另：WordPress.com 默认禁用真实的系统 WP-Cron（由平台侧定时器或页面访问触发），
 *   故不能假设「每月 1 号准点执行」。审计本身就是这个现实的对策。
 *
 * 硬性约束：本文件不产生任何面向前端的内容；禁吉凶谶纬。
 */

if (!defined('ABSPATH')) {
    exit;
}

const KCJ_ASTRO_CRON_MONTHLY   = 'kcj_astro_cron_monthly';
const KCJ_ASTRO_CRON_QUARTERLY = 'kcj_astro_cron_quarterly';

/** 注册自定义排程周期（季度 = 3 个月） */
add_filter('cron_schedules', function ($schedules) {
    if (!isset($schedules['kcj_quarterly'])) {
        $schedules['kcj_quarterly'] = array(
            'interval' => 3 * MONTH_IN_SECONDS,
            'display'  => '每季度（天象数据集扩充）',
        );
    }
    return $schedules;
});

/**
 * 排程：每月 1 号（未来 12 个月）与每季度首月（历史数据集）。
 * 用 wp_schedule_event 的首次时间戳对齐到「下一个 1 号 03:00（站点时区）」。
 */
function kcj_astro_cron_next_first_day() {
    $now = current_time('timestamp');
    $y   = (int) date('Y', $now);
    $m   = (int) date('n', $now);
    $next = mktime(3, 0, 0, $m + 1, 1, $y);
    return $next ? $next : $now + DAY_IN_SECONDS;
}

function kcj_astro_cron_schedule() {
    $next = kcj_astro_cron_next_first_day();
    if (!wp_next_scheduled(KCJ_ASTRO_CRON_MONTHLY)) {
        wp_schedule_event($next, 'monthly', KCJ_ASTRO_CRON_MONTHLY);
    }
    if (!wp_next_scheduled(KCJ_ASTRO_CRON_QUARTERLY)) {
        wp_schedule_event($next, 'kcj_quarterly', KCJ_ASTRO_CRON_QUARTERLY);
    }
}

function kcj_astro_cron_unschedule() {
    foreach (array(KCJ_ASTRO_CRON_MONTHLY, KCJ_ASTRO_CRON_QUARTERLY) as $hook) {
        $ts = wp_next_scheduled($hook);
        if ($ts) {
            wp_unschedule_event($ts, $hook);
        }
        wp_clear_scheduled_hook($hook);
    }
}

/* --------------------------- 新鲜度审计 --------------------------- */

/**
 * 数据新鲜度：最新日记录日期距今天多少天。
 * 判定：≤2 天 = 新鲜；>2 天 = 滞后（提醒补跑）；无数据 = 未导入。
 */
function kcj_astro_freshness() {
    $latest = KCJ_Astro_DB::latest_daily_date();
    $out = array(
        'latest_date_str' => $latest,
        'lag_days'        => null,
        'state'           => 'empty',
        'checked_at'      => current_time('mysql'),
    );
    if (!$latest) {
        return $out;
    }
    $today = current_time('Y-m-d');
    $d1 = strtotime($latest . ' 00:00:00');
    $d2 = strtotime($today . ' 00:00:00');
    if ($d1 !== false && $d2 !== false) {
        $out['lag_days'] = (int) round(($d2 - $d1) / DAY_IN_SECONDS);
        $out['state']    = ($out['lag_days'] <= 2) ? 'fresh' : 'stale';
    }
    return $out;
}

/** 审计并落盘（同时清缓存） */
function kcj_astro_run_audit($reason = '') {
    $fresh = kcj_astro_freshness();
    $fresh['reason'] = $reason;
    update_option('kcj_astro_freshness', $fresh, false);
    kcj_astro_forecast_flush_cache();
    return $fresh;
}

add_action(KCJ_ASTRO_CRON_MONTHLY, function () {
    // ① 广播重算需求（自建站点可挂此 action 去跑本地脚本）
    do_action('kcj_astro_need_recompute', array('scope' => 'future_12_months', 'months' => 12));
    // ② 审计 + 清缓存
    kcj_astro_run_audit('monthly');
});

add_action(KCJ_ASTRO_CRON_QUARTERLY, function () {
    do_action('kcj_astro_need_recompute', array('scope' => 'historical_expand'));
    kcj_astro_run_audit('quarterly');
});

/* --------------------------- 后台提醒 --------------------------- */

/**
 * 数据滞后 / 未导入时在后台出提示。
 * 不在前端出任何提示（前端缺数据由短代码自身的兜底文案处理）。
 */
add_action('admin_notices', function () {
    if (!current_user_can('edit_posts')) {
        return;
    }
    $fresh = get_option('kcj_astro_freshness');
    if (!is_array($fresh)) {
        return;
    }
    if ($fresh['state'] === 'fresh') {
        return;
    }
    $msg = ($fresh['state'] === 'empty')
        ? '天象数据表尚无日记录，请先在本机运行 python/build_dataset.py 并推送入库。'
        : sprintf('天象数据已滞后 %d 天（最新日记录 %s），请补跑构建脚本并推送。',
                  (int) $fresh['lag_days'], $fresh['latest_date_str']);
    printf(
        '<div class="notice notice-warning"><p><strong>嘉言一得天象模块：</strong>%s</p>'
        . '<p>推送命令示例：<code>python python/build_dataset.py --start 2027-01-01 --end 2027-12-31 '
        . '--push --wp-site %s --wp-user &lt;用户名&gt; --wp-app-password &lt;应用程序密码&gt;</code></p>'
        . '<p>校验端点：<code>GET /wp-json/kcj-astro/v1/health</code></p></div>',
        esc_html($msg),
        esc_html(home_url())
    );
});

/** 仪表盘小组件：一眼看到三表行数与新鲜度 */
add_action('wp_dashboard_setup', function () {
    if (!current_user_can('edit_posts')) {
        return;
    }
    wp_add_dashboard_widget('kcj_astro_status', '天象模块状态', function () {
        $h = KCJ_Astro_DB::health();
        echo '<ul style="margin:0">';
        foreach ($h as $k => $v) {
            printf(
                '<li>%s：%s%s</li>',
                esc_html($k),
                $v['exists'] ? '已建' : '<strong>缺表</strong>',
                ($v['rows'] !== null) ? '（' . (int) $v['rows'] . ' 行）' : ''
            );
        }
        $f = get_option('kcj_astro_freshness');
        printf(
            '<li>数据新鲜度：%s</li></ul>',
            esc_html(is_array($f) ? sprintf('%s（最新 %s，滞后 %s 天）', $f['state'],
                (string) $f['latest_date_str'], (string) $f['lag_days']) : '尚未审计')
        );
        printf('<p style="margin:6px 0 0">REST 自检：<code>%s</code></p>',
            esc_html(rest_url(KCJ_ASTRO_REST_NS . '/health')));
    });
});
