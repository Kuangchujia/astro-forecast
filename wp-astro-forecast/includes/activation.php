<?php
/**
 * 激活 / 停用（薄壳）
 *
 * ★ v1.2.0 整改（F20）：
 *   v1.1.0 在本文件里既建表、又 register_post_type()。后者是错的——
 *   自定义文章类型必须在**每个请求**的 init 阶段注册，而激活钩子只执行一次，
 *   于是激活之后 astro_event 在每次请求里都是「未注册」，详情页/归档页必然 404。
 *   CPT 与分类法的注册已整体移交 includes/cpt.php（挂 init），本文件只负责：
 *     · 建表（委托 KCJ_Astro_DB::create()，表结构正本在 includes/class-astro-db.php）
 *     · 排程定时任务（委托 includes/cron.php）
 *     · 落 schema 版本、flush 重写规则
 *   并新增停用时的对称清理（撤排程）。
 */

if (!defined('ABSPATH')) {
    exit;
}

function kcj_astro_forecast_activate() {
    KCJ_Astro_DB::create();          // 三张自定义表（表结构版本由它自己落账，见 ★F24）
    kcj_astro_cron_schedule();       // 月/季定时任务
    // ★ F24（v1.2.1 修）：原先此处写的是
    //     update_option('kcj_astro_schema_version', KCJ_ASTRO_VER);
    //   把**插件版本**写进了**表结构版本**的 option；而 KCJ_Astro_DB::create() 写的是
    //   KCJ_ASTRO_SCHEMA。同一个 option 两处语义不同 —— 一旦两者取值撞车，
    //   init 守卫就会误判「已升级」而永久跳过 ALTER，表结构再也升不上来
    //   （与 F22 同族的静默失败）。现只由 create() 一处负责落账，此处不再写。
    update_option('kcj_astro_activated_at', current_time('mysql'), false);

    // CPT/分类法在 init 上注册；激活当次请求需手动触发一次，重写规则才带得上它们
    if (function_exists('kcj_astro_register_cpt')) {
        kcj_astro_register_cpt();
    }
    flush_rewrite_rules();

    // 首次审计，便于后台立刻看到「尚无数据」而不是一片空白
    if (function_exists('kcj_astro_run_audit')) {
        kcj_astro_run_audit('activate');
    }

    // ★ v2.2.5：激活即写一次公开状态信标 —— 这样「上传并启用」这件事
    //   在站外**立刻**可见（否则要等人打开一次导入页，才有文件可读）。
    if (function_exists('kcj_astro_beacon_write')) {
        kcj_astro_beacon_write(array('run' => 'activate'));
    }
}

function kcj_astro_forecast_deactivate() {
    kcj_astro_cron_unschedule();
    flush_rewrite_rules();
}

/**
 * 数据纪元（v2.2.6）。
 *
 * 为什么需要它：本轮线上出现过「导入明明跑完了（daily_site 在库 29,298 行），前台却仍说
 * 『需导入 wp_astro_daily_site』、观测地下拉里一个城也没有」。清缓存函数当时是**直接
 * DELETE FROM wp_options**，而 WordPress.com 有**持久对象缓存** —— transient 的值可能在
 * 对象缓存里，删表删不掉它；于是「清了缓存而页面还是旧的」。
 *
 * 做法：给缓存键加一个**单调递增的纪元号**。数据一变就把纪元 +1 ⇒ 所有旧键**按定义失效**，
 * 完全不依赖「我能不能把那一项删掉」。取值用自动加载的 option，命中即内存数组，代价可忽略。
 */
function kcj_astro_data_epoch() {
    return (int) get_option('kcj_astro_data_epoch', 1);
}

/**
 * 缓存清理：删掉本插件所有 transient，并把数据纪元 +1。
 * 构建流水线推送数据后由 REST /import 成功后自动调用（F9），
 * 也可由站点自身在需要时调 do_action('kcj_astro_refresh_cache')。
 *
 * ★★ v2.2.6 两条修（都是「看着清了、其实没清」）：
 *   ① 只删 wp_options 不够 —— 持久对象缓存里还留着值。改为**逐键 delete_transient()**
 *      （它会同时清对象缓存与 options 表），再补一次原地的 DELETE 收尾。
 *      先查键名再逐键清：键名从 options 表读，故不依赖对象缓存。
 *   ② 更根本的一层：**加纪元号**（见 kcj_astro_data_epoch()）。哪怕某个缓存后端
 *      连 delete_transient 都穿不透，纪元一变旧键也不再被命中。
 *      两层同时做：一层清得掉就够，清不掉还有另一层兜。
 */
function kcj_astro_forecast_flush_cache() {
    global $wpdb;

    // ① 纪元 +1（最快、最不依赖后端能力的一层）
    update_option('kcj_astro_data_epoch', kcj_astro_data_epoch() + 1, true);

    // ② 逐键清除（穿透对象缓存）
    $names = $wpdb->get_col(
        "SELECT option_name FROM {$wpdb->options}
         WHERE option_name LIKE '_transient_kcj_astro_%'"
    );
    if (is_array($names)) {
        foreach ($names as $n) {
            $key = preg_replace('/^_transient_/i', '', (string) $n);
            if ($key !== '') {
                delete_transient($key);
            }
        }
    }

    // ③ 原地兜底（清掉可能已被 delete_transient 删掉的行，以及 timeout 行）
    $wpdb->query(
        "DELETE FROM {$wpdb->options}
         WHERE option_name LIKE '_transient_kcj_astro_%'
            OR option_name LIKE '_transient_timeout_kcj_astro_%'"
    );
}
