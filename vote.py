# -*-coding:utf-8-*-

"""
使用 Redis 构建一个简单的文章投票网站

首先要做的就是为这个网站设置一些限制条件：如果一篇文章获得了至少 200 张支持票，那么网站就认为这篇文章是一篇有趣的文章；
假如这个网站每天发布 1000 篇文章，而其中的 50 篇符合网站对有趣文章的要求，那么网站要做的就是把这 50 篇文章放到文章列表前 100 位至少一天；
另外，这个网站暂时不提供投反对票的功能。


为了产生一个能够随着时间流逝而不断减少的评分，程序需要根据文章的发布时间和当前时间来计算文章的评分，
具体的计算方法为：将文章得到的支持票数量乘以一个常量（432，这个常量是通过将一天的秒数(86400)除以文章展示一天所需的支持票数量(200)得出的，
所以文章每获得一张支持票，程序就需要将文章的评分增加 432 分），
然后加上文章的发布时间，得出的结果就是文章的评分。


构建文章投票网站除了需要计算文章评分之外，还需要使用散列来存储文章信息（包括文章的标题，指向文章的网址，发布文章的用户，文章的发布时间，文章得到的投票数量等）。
定义散列的 key 为：article:ID（文章 ID）


使用两个有序集合来有序地存储文章：
第一个有序集合的 key 为：time:   成员为：article:ID（文章 ID） 分值为文章的发布时间
第二个有序集合的 key 为：score:  成员为：article:ID（文章 ID） 分值为文章的评分
通过这两个有序集合，网站既可以根据文章发布的先后顺序来展示文章，又可以根据文章评分的高低来展示文章。


为了防止用户对同一篇文章进行多次投票，需要为每篇文章纪录一个已投票用户名单。为此，为每篇文章创建一个集合，并使用这个集合来存储所有已投票用户的 ID
定义集合的 key 为：voted:ID（文章 ID）
为了尽量节约内存，规定当一篇文章发布期满一周之后，用户将不能再对其进行投票，文章的评分将被固定下来，而纪录文章已投票用户名单的集合也会被删除。


Redis 不仅可以对多个集合执行操作，甚至在一些情况下，还可以在集合和有序集合之间执行操作。
为了能够根据评分对群组文章进行排序和分页，需要将同一个群组里面的所有文章都按照评分有序地存储到一个有序集合里面。
ZINTERSTORE 命令可以接受多个集合和多个有序集合作为输入，找出所有同时存在于集合和有序集合的成员，并以几种不同的方式来合并这些成员的分值（所有集合成员的分值都被视为是 1）。
通过对存储群组文章的集合和存储文章评分的有序集合执行 ZINTERSTORE 命令，可以得到按照文章评分排序的群组文章；
通过对存储群组文章的集合和存储文章发布时间的有序集合执行 ZINTERSTORE 命令，可以得到按照文章发布时间排序的群组文章；
有的网站只允许用户将文章放在一个或者两个群组里面（其中一个是"所有文章"群组，另一个是最适合文章的群组）。在这种情况下，最好直接将文章所在的群组纪录到存储文章信息的散列里面，
并在 article_vote() 函数的末尾增加一个 ZINCRBY 命令调用，用于更新文章在群组中的评分。
但是在这个示例里面，我们构建的文章投票网站允许一篇文章同时属于多个群组，所以对于一篇同时属于多个群组的文章来说，更新文章的评分意味着需要对文章所属的全部群组执行自增操作，
这一操作可能会变得相当耗时。
"""

import time
import redis

redis_conn = redis.Redis(host='localhost', port=6379, db=0)

ONE_WEEK_IN_SECONDS = 7 * 86400
VOTE_SCORE = 432
ARTICLES_PER_PAGE = 25


def article_vote(conn, user, article):
    """
    对文章进行投票
    :param conn:
    :param user:
    :param article:
    :return:
    """
    # 使用 ZSCORE 命令检查纪录文章发布时间的有序集合，判断文章的发布时间是否未超过一周
    if conn.zscore('time:', article) + ONE_WEEK_IN_SECONDS < time.time():
        return

    # 从 article:ID 里面取出文章的 ID
    article_id = article.partition(':')[-1]

    # 使用 SADD 命令尝试将用户添加到纪录文章已投票用户名单的集合里面，如果添加成功，说明用户是第一次为这篇文章投票，那么增加这篇文章的投票数量和评分
    if conn.sadd('voted:' + article_id, user):
        conn.zincrby('score:', article, amount=VOTE_SCORE)
        conn.hincrby(article, 'votes', amount=1)


def post_article(conn, user, title, link):
    """
    发布文章
    :param conn:
    :param user:
    :param title:
    :param link:
    :return:
    """
    # 生成一个新的文章 ID
    article_id = conn.incr('article:')

    # 将发布文章的用户添加到文章已投票用户名单的集合里面，然后将这个名单的过期时间设置为一周
    voted = 'voted:' + article_id
    conn.sadd(voted, user)
    conn.expire(voted, ONE_WEEK_IN_SECONDS)

    # 将文章的信息存储到一个散列里面
    now = time.time()
    article = 'article:' + article_id
    conn.hmset(article, {
        'title': title,
        'link': link,
        'poster': user,
        'time': now,
        'votes': 1
    })

    # 将文章的初始评分和发布时间分别添加到两个相应的有序集合
    conn.zadd('score:', article, now + VOTE_SCORE)
    conn.zadd('time:', article, now)


def get_articles(conn, page, order='score:'):
    """
    分页获取文章
    :param conn:
    :param page:
    :param order:
    :return:
    """
    # 设置起始索引和结束索引
    start = (page - 1) * ARTICLES_PER_PAGE
    end = start + ARTICLES_PER_PAGE - 1
    # 使用 ZREVRANGE 命令以分值从大到小的排列顺序取出多个文章 ID
    ids = conn.zrevrange(order, start, end)
    articles = []
    for id in ids:
        # 根据文章 ID 获取文章的详细信息
        article_data = conn.hgetall(id)
        article_data['id'] = id
        articles.append(article_data)
    return articles


def add_remove_groups(conn, article, to_add=[], to_remove=[]):
    """
    对文章进行分组
    :param conn:
    :param article:
    :param to_add:
    :param to_remove:
    :return:
    """
    # 将文章添加到所属的群组
    for group in to_add:
        conn.sadd('group:' + group, article)

    # 从群组里面移除文章
    for group in to_remove:
        conn.srem('group:' + group, article)


def get_group_articles(conn, group, page, order='score:'):
    """
    分页获取分组文章
    :param conn:
    :param group:
    :param page:
    :param order:
    :return:
    """
    key = order + group
    # 检查是否有已缓存的排序结果
    if not conn.exists(key):
        # 使用 ZINTERSTORE 命令产生新的有序集合
        conn.zinterstore(key, ['group:' + group, order], aggregate='max')
        # 对结果进行缓存处理，设置过期时间为 60 秒
        conn.expire(key, 60)
    return get_articles(conn, page, key)
