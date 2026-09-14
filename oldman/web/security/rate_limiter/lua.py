"""Lua programs used by Redis-backed Web security rate limiting."""

# ruff: noqa: W291 - The Lua literal keeps its original trailing whitespace; do not reformat it.

FINGERPRINT_IP_RATE_LIMIT_LUA = """
-- rate_limit_atomic.lua
-- 多维度原子化限流脚本
-- 
-- KEYS[1-6]: 由Python预先拼接好的完整key名称
-- KEYS[1]: 指纹限流key (rate:fp:{fingerprint})
-- KEYS[2]: IP限流key (rate:ip:{ip})
-- KEYS[3]: 指纹-IP关联key (relation:fp_ip:{fingerprint})
-- KEYS[4]: IP-指纹关联key (relation:ip_fp:{ip})
-- KEYS[5]: 指纹黑名单key (blacklist:fp:{fingerprint})
-- KEYS[6]: IP黑名单key (blacklist:ip:{ip})
-- KEYS[7]: 指纹违规计数key (violations:fp:{fingerprint})
-- KEYS[8]: IP违规计数key (violations:ip:{ip})
--
-- ARGV[1]: 当前时间戳
-- ARGV[2]: 时间窗口（秒）
-- ARGV[3]: 指纹最大请求数
-- ARGV[4]: IP最大请求数
-- ARGV[5]: 自动拉黑阈值
-- ARGV[6]: 同IP最大指纹数
-- ARGV[7]: 同指纹最大IP数
-- ARGV[8]: 违规计数过期时间
-- ARGV[9]: 黑名单持续时间
-- ARGV[10]: 当前请求的唯一标识

local fp_rate_key = KEYS[1]
local ip_rate_key = KEYS[2]
local fp_ip_rel_key = KEYS[3]
local ip_fp_rel_key = KEYS[4]
local fp_blacklist_key = KEYS[5]
local ip_blacklist_key = KEYS[6]
local fp_violation_key = KEYS[7]
local ip_violation_key = KEYS[8]

local current_time = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local fp_max_requests = tonumber(ARGV[3])
local ip_max_requests = tonumber(ARGV[4])
local blacklist_threshold = tonumber(ARGV[5])
local max_fp_per_ip = tonumber(ARGV[6])
local max_ip_per_fp = tonumber(ARGV[7])
local violation_ttl = tonumber(ARGV[8])
local blacklist_duration = tonumber(ARGV[9])
local request_id = ARGV[10]
local ip = ARGV[11]
local fingerprint = ARGV[12]

-- 1. 黑名单检查
if redis.call("EXISTS", fp_blacklist_key) == 1 then
    return {0, "fingerprint_blocked", 0, 0, ""}
end

if redis.call("EXISTS", ip_blacklist_key) == 1 then
    return {0, "ip_blocked", 0, 0, ""}
end

-- 2. 清理过期请求（滑动窗口）
local window_start = current_time - window
redis.call("ZREMRANGEBYSCORE", fp_rate_key, 0, window_start)
redis.call("ZREMRANGEBYSCORE", ip_rate_key, 0, window_start)

-- 3. 统计当前窗口内的请求数
local fp_count = redis.call("ZCARD", fp_rate_key)
local ip_count = redis.call("ZCARD", ip_rate_key)

-- 4. 检查指纹限流
if fp_count >= fp_max_requests then
    local violations = redis.call("INCR", fp_violation_key)
    redis.call("EXPIRE", fp_violation_key, violation_ttl)

    if violations >= blacklist_threshold then
        redis.call("SETEX", fp_blacklist_key, blacklist_duration, "auto_blocked")
    end

    return {0, "rate_limit_exceeded_fp", fp_count, ip_count, ""}
end

-- 5. 检查IP限流
if ip_count >= ip_max_requests then
    local violations = redis.call("INCR", ip_violation_key)
    redis.call("EXPIRE", ip_violation_key, violation_ttl)

    if violations >= blacklist_threshold then
        redis.call("SETEX", ip_blacklist_key, blacklist_duration, "auto_blocked")
    end

    return {0, "rate_limit_exceeded_ip", fp_count, ip_count, ""}
end

-- 6. 记录请求（使用唯一request_id避免重复）
redis.call("ZADD", fp_rate_key, current_time, request_id)
redis.call("EXPIRE", fp_rate_key, window)

redis.call("ZADD", ip_rate_key, current_time, request_id)
redis.call("EXPIRE", ip_rate_key, window)

-- 7. 更新IP-指纹关联关系
redis.call("SADD", fp_ip_rel_key, ip)
redis.call("EXPIRE", fp_ip_rel_key, 86400)

redis.call("SADD", ip_fp_rel_key, fingerprint)
redis.call("EXPIRE", ip_fp_rel_key, 86400)

-- 8. 异常行为检测
local fp_ip_count = redis.call("SCARD", fp_ip_rel_key)
local ip_fp_count = redis.call("SCARD", ip_fp_rel_key)

local anomalies = {}
if ip_fp_count > max_fp_per_ip then
    table.insert(anomalies, "multi_fingerprint_per_ip")
end

if fp_ip_count > max_ip_per_fp then
    table.insert(anomalies, "multi_ip_per_fingerprint")
end

-- 返回：{允许, 原因, 指纹计数, IP计数, 异常标志}
return {1, "allowed", fp_count + 1, ip_count + 1, table.concat(anomalies, ",")}
"""
