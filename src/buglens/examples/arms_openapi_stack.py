# -*- coding: utf-8 -*-
# This file is auto-generated, don't edit it. Thanks.
import os
import sys
import json

from typing import List

from alibabacloud_arms20190808.client import Client as ARMS20190808Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_arms20190808 import models as arms20190808_models
# from alibabacloud_tea_util import models as util_models
from darabonba.runtime import RuntimeOptions
from alibabacloud_tea_util.client import Client as UtilClient
import asyncio
from alibabacloud_credentials.models import Config as CredentialConfig
import os
from dotenv import load_dotenv

class Sample:
    def __init__(self):
        pass

    @staticmethod
    def create_client() -> ARMS20190808Client:
        """
        使用凭据初始化账号Client
        @return: Client
        @throws Exception
        """
        # 工程代码建议使用更安全的无AK方式，凭据配置方式请参见：https://help.aliyun.com/document_detail/378659.html。
        # credential = CredentialClient()
        credentialsConfig = CredentialConfig(
            type='access_key',
            # 必填参数，此处以从环境变量中获取AccessKey ID为例
            access_key_id=os.environ.get('BUGLENS_ALIBABA_ACCESS_KEY_ID', ''),
            # 必填参数，此处以从环境变量中获取AccessKey Secret为例
            access_key_secret=os.environ.get('BUGLENS_ALIBABA_ACCESS_KEY_SECRET', '')
        )
        credentialsClient = CredentialClient(credentialsConfig)

        config = open_api_models.Config(
            credential=credentialsClient
        )
        # Endpoint 请参考 https://api.aliyun.com/product/ARMS
        config.endpoint = f'arms.cn-hangzhou.aliyuncs.com'
        return ARMS20190808Client(config)
    
    @staticmethod
    def create_api_info() -> open_api_models.Params:
        """
        API 相关
        @param path: string Path parameters
        @return: OpenApi.Params
        """
        params = open_api_models.Params(
            # 接口名称,
            action='GetRumExceptionStack',
            # 接口版本,
            version='2019-08-08',
            # 接口协议,
            protocol='HTTPS',
            # 接口 HTTP 方法,
            method='POST',
            auth_type='AK',
            style='V3',
            # 接口 PATH,
            pathname=f'/',
            # 接口请求体内容格式,
            req_body_type='json',
            # 接口响应体内容格式,
            body_type='json'
        )
        return params


async def main():
    load_dotenv()
    client = Sample.create_client()
    params = Sample.create_api_info()
    runtime = RuntimeOptions()
    try:
        request = open_api_models.OpenApiRequest()
        resp = client.call_api(params, request, runtime)
        print(json.dumps(resp, default=str, indent=2))
    except Exception as error:
        # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
        # 错误 message
        # print(error.message)
        # 诊断地址
        # print(error.data.get("Recommend"))
        print(error)

if __name__ == '__main__':
    asyncio.run(main())