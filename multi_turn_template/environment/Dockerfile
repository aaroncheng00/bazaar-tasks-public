FROM python:3.11-slim
WORKDIR /app
COPY repo/ /app/
# anti-cheat: no docs shipped into the image
RUN rm -rf /app/docs 2>/dev/null || true
# guard: the incomplete/buggy helper the cascade builds on MUST be present in the base
RUN grep -q "BUG:" /app/pkg/module.py
RUN git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -q -m base
