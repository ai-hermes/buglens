# -*- coding: utf-8 -*-
# This file is auto-generated, don't edit it. Thanks.
import os
import sys
import json

from typing import List

from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_credentials.models import Config as CredentialConfig
from darabonba.runtime import RuntimeOptions
from dotenv import load_dotenv
from alibabacloud_openapi_util.client import Client as OpenApiUtilClient



class Sample:
    def __init__(self):
        pass

    @staticmethod
    def create_client() -> OpenApiClient:
        """
        使用凭据初始化账号Client
        @return: Client
        @throws Exception
        """
        # 工程代码建议使用更安全的无AK方式，凭据配置方式请参见：https://help.aliyun.com/document_detail/378659.html。
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
        return OpenApiClient(config)

    @staticmethod
    def create_api_info() -> open_api_models.Params:
        """
        API 相关
        @param path: string Path parameters
        @return: OpenApi.Params
        """
        params = open_api_models.Params(
            # 接口名称,
            action='GetRumDataForPage',
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

    @staticmethod
    def main(
        args: List[str],
    ) -> None:
        load_dotenv()
        client = Sample.create_client()
        params = Sample.create_api_info()
        # query params
        queries = {}
        queries['Query'] = '* and (app.type : browser or app.type : miniapp) and event_type: exception '
        queries['StartTime'] = 1779428866
        queries['EndTime'] = 1779429946
        queries['PageSize'] = 100
        queries['CurrentPage'] = 1
        queries['RegionId'] = 'cn-hangzhou'
        # runtime options
        runtime = RuntimeOptions()
        request = open_api_models.OpenApiRequest(
            query=OpenApiUtilClient.query(queries)
        )
        # 返回值实际为 Map 类型，可从 Map 中获得三类数据：响应体 body、响应头 headers、HTTP 返回的状态码 statusCode。
        resp = client.call_api(params, request, runtime)
        print(json.dumps(resp, ensure_ascii=False, default=str, indent=2))



if __name__ == '__main__':
    Sample.main(sys.argv[1:])
