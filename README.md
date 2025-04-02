# HTTP请求工具

一个功能强大的HTTP请求工具插件，支持多种请求方式和类curl格式命令，并能自动使用AI总结响应内容。

## 使用方法

### 基本命令

- **GET请求**: `/get https://api.example.com`
- **POST请求**: `/post https://api.example.com {"key": "value"}`
- **自定义请求**: `/request METHOD URL {可选参数}`

### curl格式请求

可以使用类似curl的格式发送复杂请求：

```
/请求 https://example.com -H "Content-Type: application/json" -H "Authorization: Bearer token" -X POST -d '{"key": "value"}'
```

支持的curl选项：
- `-H` 设置请求头
- `-b` 设置cookies
- `-X` 设置请求方法
- `-d` 设置请求数据

### 智能响应总结

所有HTTP请求的响应都会自动使用大语言模型进行智能总结，包括：
- 返回的主要数据内容
- 数据的结构特点
- 可能的用途或含义

如果响应内容较短（少于100个字符），将直接显示原始内容而不进行总结。

## 示例

发送带有多个头信息的GET请求：
```
/请求 https://www.example.com -H "User-Agent: Mozilla/5.0" -H "Accept: application/json"
```

发送POST请求并附带数据：
```
/请求 https://api.example.com -X POST -H "Content-Type: application/json" -d '{"name": "test", "value": 123}'
```

使用cookie发送请求：
```
/请求 https://www.example.com -b "session=abc123; user=john"
```
