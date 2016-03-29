import time
import redis

redis_conn = redis.Redis(host='localhost', port=6379, db=0)

ONE_WEEK_IN_SECONDS = 7 * 86400
VOTE_SCORE = 432


def article_vote(conn, user, article):

	# 计算文章投票截止时间
	cutoff = int(time.time()) - ONE_WEEK_IN_SECONDS

	if conn.zscore('time:', article) < cutoff:
		return

	# 从article:id标识符（identifier）里面取出文章的ID
	article_id = article.partition(':')[-1]

	# 如果用户是第一次为这篇文章投票，那么增加这篇文章的投票数量和评分
	if conn.sadd('voted:' + article_id, user):
		conn.zincrby('score:', article, amount=VOTE_SCORE)
		conn.hincrby(article, 'votes', amount=1)


def post_article(conn, user, title, link):
	conn = redis_conn
	article_id = conn.incr('article:')

	now = int(time.time())
	article = 'article:' + article_id
	data = {
		'title': title,
		'link': link,
		'poster': user,
		'time': now,
		'votes': 1
	}
	conn.hmset(article, data)

	voted = 'voted:' + article_id
	conn.sadd(voted, user)
	conn.expire(voted, ONE_WEEK_IN_SECONDS)

	conn.zadd('time:', article, now)
	conn.zadd('score:', article, now + VOTE_SCORE)